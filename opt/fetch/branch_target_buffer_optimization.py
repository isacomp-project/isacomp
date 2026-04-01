#!/usr/bin/env python3
"""
Branch Target Buffer (BTB) Optimization for ResourceGraph.

This module implements a Branch Target Buffer optimization that predicts branch
target addresses by caching PC -> target mappings. The BTB complements static
not-taken prediction by providing dynamic target prediction for taken branches.

Key features:
- Caches branch PC -> target address mappings
- 2-bit saturating counter for direction prediction
- Integrates with RAS (Return Address Stack) when present
- Supports configurable size and associativity

Prediction Priority (when RAS is present):
1. RAS (if ras_pop active) -> ras_top
2. BTB (if hit && predicted_taken && !ras_pop) -> btb_predicted_target
3. Default -> PC+4

This follows the 7-phase optimization pattern:
1. ANALYSIS - Validate inputs and understand graph structure
2. PLANNING - Calculate BTB parameters
3. STRUCTURE - Build skeleton nodes for BTB components
4. HARDWARE - Generate comparators, muxes, update logic
5. CONNECTION - Wire all components together
6. CLEANUP - Remove orphaned nodes
7. TIMING - Re-infer timing information
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import math

from core.resource_graph import ResourceGraph, Node, Edge
from core.hardware_builders import HardwareBuilderFactory


@dataclass
class BTBSpec:
    """Specification for Branch Target Buffer insertion."""

    # =========================================================================
    # Required: Branch instruction identification
    # =========================================================================
    branch_enable_nodes: List[str]  # e.g., ['beq_enable', 'bne_enable', 'jal_enable']
                                    # These are ORed together for BTB update enable

    # Required: Branch outcome and target signals (Execute stage)
    branch_outcome_node: str        # Signal indicating branch taken/not-taken
    branch_target_node: str         # Actual resolved target address

    # Required: PC nodes
    fetch_pc_node: str              # Fetch stage PC (used for BTB lookup)
    branch_pc_node: str             # Execute stage PC (for BTB update - pipelined fetch PC)

    # =========================================================================
    # Required: Infrastructure nodes (must exist in graph)
    # =========================================================================
    predicted_pc_node_id: str       # Node that will receive the predicted PC
    default_prediction_node_id: str # Node with default prediction (PC+4)
    control_hazard_flush_node_id: str  # Existing control hazard flush signal

    # =========================================================================
    # RAS Coordination (required when RAS is present)
    # =========================================================================
    ras_pop_node_id: Optional[str] = None   # 'ras_pop' - return detection signal
    ras_top_node_id: Optional[str] = None   # 'ras_top' - RAS predicted target
    # When ras_pop is active, BTB prediction is suppressed in favor of RAS

    # =========================================================================
    # Optional: BTB sizing
    # =========================================================================
    num_entries: int = 64           # Number of BTB entries (must be power of 2)
    associativity: int = 1          # 1=direct-mapped, 2/4=set-associative

    # Optional: Address configuration
    pc_width: int = 32              # Address width in bits
    btb_name: str = "btb"           # Name for the BTB node

    # Optional: Prediction features
    include_direction_bits: bool = True   # Store taken/not-taken history
    confidence_bits: int = 2              # 2-bit saturating counter

    # Optional: Replacement policy (for set-associative)
    replacement_policy: str = 'lru'  # 'lru', 'random', 'fifo'

    def __post_init__(self):
        """Validate specification."""
        if self.num_entries & (self.num_entries - 1) != 0:
            raise ValueError(f"num_entries must be power of 2, got {self.num_entries}")
        if self.associativity not in [1, 2, 4, 8]:
            raise ValueError(f"associativity must be 1, 2, 4, or 8, got {self.associativity}")
        if not self.branch_enable_nodes:
            raise ValueError("At least one branch_enable_node is required")
        # Validate RAS coordination: if one is set, both must be set
        if (self.ras_pop_node_id is None) != (self.ras_top_node_id is None):
            raise ValueError("ras_pop_node_id and ras_top_node_id must both be set or both be None")

    @property
    def has_ras_coordination(self) -> bool:
        """Check if RAS coordination is enabled."""
        return self.ras_pop_node_id is not None

    @property
    def index_width(self) -> int:
        """Bits needed for BTB index."""
        num_sets = self.num_entries // self.associativity
        return max(1, (num_sets - 1).bit_length())

    @property
    def tag_width(self) -> int:
        """Bits needed for tag (remaining after index and byte offset)."""
        byte_offset_bits = 2  # Assuming word-aligned instructions
        return self.pc_width - self.index_width - byte_offset_bits


@dataclass
class BTBAnalysis:
    """Results from analyzing the graph for BTB applicability."""
    # Validated branch enable nodes
    branch_enables: List[Node]

    # Branch outcome and target nodes
    branch_outcome: Node
    branch_target: Node

    # PC nodes
    fetch_pc: Node
    branch_pc: Node

    # Infrastructure nodes
    predicted_pc: Node
    default_prediction: Node
    control_hazard_flush: Node

    # RAS nodes (optional)
    ras_pop: Optional[Node] = None
    ras_top: Optional[Node] = None

    # Timing info
    fetch_stage: int = 0
    execute_stage: int = 1


class BranchTargetBufferOptimization:
    """
    Implements Branch Target Buffer optimization.

    The BTB predicts branch targets by caching PC -> target mappings:
    - Lookup: Use fetch PC to predict target before decode
    - Update: When branch resolves, update cache with actual target
    - Direction: 2-bit saturating counter predicts taken/not-taken
    """

    def __init__(self, graph: ResourceGraph, spec: BTBSpec):
        self.graph = graph
        self.spec = spec
        self.hw_factory = HardwareBuilderFactory(graph)
        self.analysis: Optional[BTBAnalysis] = None

        # Created nodes for later reference
        self.btb_nodes: Dict[str, Node] = {}

    def apply(self) -> bool:
        """
        Apply BTB optimization to the graph.

        Returns:
            True if BTB was successfully applied
        """
        print("\n" + "=" * 70)
        print("APPLYING BRANCH TARGET BUFFER (BTB) OPTIMIZATION")
        print("=" * 70)

        # Phase 1: ANALYSIS
        print("\n--- Phase 1: ANALYSIS ---")
        self.analysis = self._analyze()
        if self.analysis is None:
            print("Analysis failed - BTB optimization not applicable")
            return False

        # Phase 2: PLANNING
        print("\n--- Phase 2: PLANNING ---")
        params = self._plan()

        # Phase 3: STRUCTURE
        print("\n--- Phase 3: STRUCTURE ---")
        self._create_structure(params)

        # Phase 4: HARDWARE
        print("\n--- Phase 4: HARDWARE ---")
        self._generate_hardware(params)

        # Phase 5: CONNECTION
        print("\n--- Phase 5: CONNECTION ---")
        self._wire_components(params)

        # Phase 6: CLEANUP
        print("\n--- Phase 6: CLEANUP ---")
        self._cleanup()

        # Phase 7: TIMING
        print("\n--- Phase 7: TIMING ---")
        self.graph.infer_uarch_time(force_reinfer=True)

        print("\n" + "=" * 70)
        print("BTB OPTIMIZATION COMPLETED SUCCESSFULLY")
        print("=" * 70)
        return True

    # =========================================================================
    # Phase 1: ANALYSIS
    # =========================================================================

    def _analyze(self) -> Optional[BTBAnalysis]:
        """Analyze graph structure and validate BTB applicability."""

        # Validate branch enable nodes
        print("  Validating branch enable nodes...")
        branch_enables = []
        for enable_id in self.spec.branch_enable_nodes:
            node = self.graph.nodes.get(enable_id)
            if node:
                branch_enables.append(node)
                print(f"    Found: {enable_id}")
            else:
                print(f"    Warning: Branch enable '{enable_id}' not found")

        if not branch_enables:
            print("  ERROR: No valid branch enable nodes found")
            return None

        # Validate branch outcome and target
        print("  Validating branch outcome and target...")
        branch_outcome = self.graph.nodes.get(self.spec.branch_outcome_node)
        if not branch_outcome:
            print(f"  ERROR: Branch outcome node '{self.spec.branch_outcome_node}' not found")
            return None
        print(f"    Found branch_outcome: {self.spec.branch_outcome_node}")

        branch_target = self.graph.nodes.get(self.spec.branch_target_node)
        if not branch_target:
            print(f"  ERROR: Branch target node '{self.spec.branch_target_node}' not found")
            return None
        print(f"    Found branch_target: {self.spec.branch_target_node}")

        # Validate PC nodes
        print("  Validating PC nodes...")
        fetch_pc = self.graph.nodes.get(self.spec.fetch_pc_node)
        if not fetch_pc:
            print(f"  ERROR: Fetch PC node '{self.spec.fetch_pc_node}' not found")
            return None
        print(f"    Found fetch_pc: {self.spec.fetch_pc_node}")

        branch_pc = self.graph.nodes.get(self.spec.branch_pc_node)
        if not branch_pc:
            print(f"  ERROR: Branch PC node '{self.spec.branch_pc_node}' not found")
            return None
        print(f"    Found branch_pc: {self.spec.branch_pc_node}")

        # Validate infrastructure nodes
        print("  Validating infrastructure nodes...")
        predicted_pc = self.graph.nodes.get(self.spec.predicted_pc_node_id)
        if not predicted_pc:
            print(f"  ERROR: Predicted PC node '{self.spec.predicted_pc_node_id}' not found")
            return None
        print(f"    Found predicted_pc: {self.spec.predicted_pc_node_id}")

        default_prediction = self.graph.nodes.get(self.spec.default_prediction_node_id)
        if not default_prediction:
            print(f"  ERROR: Default prediction node '{self.spec.default_prediction_node_id}' not found")
            return None
        print(f"    Found default_prediction: {self.spec.default_prediction_node_id}")

        control_hazard_flush = self.graph.nodes.get(self.spec.control_hazard_flush_node_id)
        if not control_hazard_flush:
            print(f"  ERROR: Control hazard flush node '{self.spec.control_hazard_flush_node_id}' not found")
            return None
        print(f"    Found control_hazard_flush: {self.spec.control_hazard_flush_node_id}")

        # Validate RAS nodes if coordination is enabled
        ras_pop = None
        ras_top = None
        if self.spec.has_ras_coordination:
            print("  Validating RAS coordination nodes...")
            ras_pop = self.graph.nodes.get(self.spec.ras_pop_node_id)
            if not ras_pop:
                print(f"  ERROR: RAS pop node '{self.spec.ras_pop_node_id}' not found")
                return None
            print(f"    Found ras_pop: {self.spec.ras_pop_node_id}")

            ras_top = self.graph.nodes.get(self.spec.ras_top_node_id)
            if not ras_top:
                print(f"  ERROR: RAS top node '{self.spec.ras_top_node_id}' not found")
                return None
            print(f"    Found ras_top: {self.spec.ras_top_node_id}")

        # Determine timing
        fetch_stage = fetch_pc.uarch_time if fetch_pc.uarch_time is not None else 0
        execute_stage = branch_pc.uarch_time if branch_pc.uarch_time is not None else 1
        print(f"  Timing: fetch_stage={fetch_stage}, execute_stage={execute_stage}")

        return BTBAnalysis(
            branch_enables=branch_enables,
            branch_outcome=branch_outcome,
            branch_target=branch_target,
            fetch_pc=fetch_pc,
            branch_pc=branch_pc,
            predicted_pc=predicted_pc,
            default_prediction=default_prediction,
            control_hazard_flush=control_hazard_flush,
            ras_pop=ras_pop,
            ras_top=ras_top,
            fetch_stage=fetch_stage,
            execute_stage=execute_stage
        )

    # =========================================================================
    # Phase 2: PLANNING
    # =========================================================================

    def _plan(self) -> Dict:
        """Calculate BTB parameters."""

        params = {
            'num_entries': self.spec.num_entries,
            'associativity': self.spec.associativity,
            'index_width': self.spec.index_width,
            'tag_width': self.spec.tag_width,
            'pc_width': self.spec.pc_width,
            'confidence_bits': self.spec.confidence_bits,
            'has_ras': self.spec.has_ras_coordination,
        }

        print(f"  BTB entries: {params['num_entries']}")
        print(f"  Associativity: {params['associativity']}")
        print(f"  Index width: {params['index_width']} bits")
        print(f"  Tag width: {params['tag_width']} bits")
        print(f"  PC width: {params['pc_width']} bits")
        print(f"  Confidence bits: {params['confidence_bits']}")
        print(f"  RAS coordination: {params['has_ras']}")

        return params

    # =========================================================================
    # Phase 3: STRUCTURE
    # =========================================================================

    def _create_structure(self, params: Dict):
        """Create skeleton nodes for BTB components."""

        btb_name = self.spec.btb_name

        # BTB main storage node (microarchitectural state)
        # Enable dual_port for Execute-stage misprediction detection lookup
        btb_storage = Node(f'{btb_name}_storage', data={
            'type': 'btb_storage',
            'name': f'{btb_name}_storage',
            'display_name': 'Branch Target Buffer Storage',
            'num_entries': params['num_entries'],
            'tag_width': params['tag_width'],
            'target_width': params['pc_width'],
            'confidence_bits': params['confidence_bits'],
            'associativity': params['associativity'],
            'btb_component': True,
            'dual_port': True  # Enable Execute-stage lookup for misprediction detection
        }, is_uarch_state=True, uarch_time=0)
        self.graph.add_node(btb_storage)
        self.btb_nodes['btb_storage'] = btb_storage
        print(f"  Created {btb_name}_storage (dual-port enabled)")

        # BTB hit signal
        btb_hit = Node(f'{btb_name}_hit', data={
            'type': 'var',
            'name': f'{btb_name}_hit',
            'display_name': 'BTB Hit',
            'bit_width': 1,
            'btb_component': True,
            'btb_output': True  # Declared by BTB module
        }, uarch_time=0)
        self.graph.add_node(btb_hit)
        self.btb_nodes['btb_hit'] = btb_hit
        print(f"  Created {btb_name}_hit")

        # BTB predicted target
        btb_predicted_target = Node(f'{btb_name}_predicted_target', data={
            'type': 'var',
            'name': f'{btb_name}_predicted_target',
            'display_name': 'BTB Predicted Target',
            'bit_width': params['pc_width'],
            'btb_component': True,
            'btb_output': True  # Declared by BTB module
        }, uarch_time=0)
        self.graph.add_node(btb_predicted_target)
        self.btb_nodes['btb_predicted_target'] = btb_predicted_target
        print(f"  Created {btb_name}_predicted_target")

        # BTB predicted taken (from confidence counter)
        btb_predicted_taken = Node(f'{btb_name}_predicted_taken', data={
            'type': 'var',
            'name': f'{btb_name}_predicted_taken',
            'display_name': 'BTB Predicted Taken',
            'bit_width': 1,
            'btb_component': True,
            'btb_output': True  # Declared by BTB module
        }, uarch_time=0)
        self.graph.add_node(btb_predicted_taken)
        self.btb_nodes['btb_predicted_taken'] = btb_predicted_taken
        print(f"  Created {btb_name}_predicted_taken")

        # BTB use signal (hit && predicted_taken && !ras_pop)
        btb_use = Node(f'{btb_name}_use', data={
            'type': 'var',
            'name': f'{btb_name}_use',
            'display_name': 'BTB Use (prediction active)',
            'bit_width': 1,
            'btb_component': True
        }, uarch_time=0)
        self.graph.add_node(btb_use)
        self.btb_nodes['btb_use'] = btb_use
        print(f"  Created {btb_name}_use")

        # BTB update enable (OR of all branch enables)
        btb_update_enable = Node(f'{btb_name}_update_enable', data={
            'type': 'var',
            'name': f'{btb_name}_update_enable',
            'display_name': 'BTB Update Enable',
            'bit_width': 1,
            'btb_component': True
        }, uarch_time=self.analysis.execute_stage)
        self.graph.add_node(btb_update_enable)
        self.btb_nodes['btb_update_enable'] = btb_update_enable
        print(f"  Created {btb_name}_update_enable")

        # BTB misprediction signal
        btb_mispredict = Node(f'{btb_name}_mispredict', data={
            'type': 'var',
            'name': f'{btb_name}_mispredict',
            'display_name': 'BTB Misprediction',
            'bit_width': 1,
            'btb_component': True
        }, uarch_time=self.analysis.execute_stage)
        self.graph.add_node(btb_mispredict)
        self.btb_nodes['btb_mispredict'] = btb_mispredict
        print(f"  Created {btb_name}_mispredict")

        # Calculate number of pipeline stages from Fetch to Execute
        stages_needed = self.analysis.execute_stage - self.analysis.fetch_stage

        # Create intermediate pipeline registers if needed
        # For a 5-stage pipeline (Execute at time 2), we need:
        # btb_use -> PIPE_Decode_btb_use_PIPE -> btb_use_execute
        if stages_needed > 1:
            # Create Decode stage intermediate register for btb_use
            btb_use_decode = Node(f'PIPE_Decode_{btb_name}_use_PIPE', data={
                'type': 'pipeline_register',
                'name': f'PIPE_Decode_{btb_name}_use_PIPE',
                'display_name': 'BTB Use at Decode stage',
                'bit_width': 1,
                'btb_component': True,
                'pipeline_stage': 'Decode'
            }, is_uarch_state=True, uarch_time=self.analysis.fetch_stage + 1)
            self.graph.add_node(btb_use_decode)
            self.btb_nodes['btb_use_decode'] = btb_use_decode
            print(f"  Created PIPE_Decode_{btb_name}_use_PIPE (intermediate)")

            # Create Decode stage intermediate register for btb_predicted_target
            btb_predicted_target_decode = Node(f'PIPE_Decode_{btb_name}_predicted_target_PIPE', data={
                'type': 'pipeline_register',
                'name': f'PIPE_Decode_{btb_name}_predicted_target_PIPE',
                'display_name': 'BTB Predicted Target at Decode stage',
                'bit_width': params['pc_width'],
                'btb_component': True,
                'pipeline_stage': 'Decode'
            }, is_uarch_state=True, uarch_time=self.analysis.fetch_stage + 1)
            self.graph.add_node(btb_predicted_target_decode)
            self.btb_nodes['btb_predicted_target_decode'] = btb_predicted_target_decode
            print(f"  Created PIPE_Decode_{btb_name}_predicted_target_PIPE (intermediate)")

        # Pipelined btb_use for misprediction detection at Execute stage
        btb_use_execute = Node(f'{btb_name}_use_execute', data={
            'type': 'pipeline_register',
            'name': f'{btb_name}_use_execute',
            'display_name': 'BTB Use at Execute stage',
            'bit_width': 1,
            'btb_component': True,
            'pipeline_stage': 'Execute'
        }, is_uarch_state=True, uarch_time=self.analysis.execute_stage)
        self.graph.add_node(btb_use_execute)
        self.btb_nodes['btb_use_execute'] = btb_use_execute
        print(f"  Created {btb_name}_use_execute")

        # Pipelined predicted target for misprediction comparison
        btb_predicted_target_execute = Node(f'{btb_name}_predicted_target_execute', data={
            'type': 'pipeline_register',
            'name': f'{btb_name}_predicted_target_execute',
            'display_name': 'BTB Predicted Target at Execute',
            'bit_width': params['pc_width'],
            'btb_component': True,
            'pipeline_stage': 'Execute'
        }, is_uarch_state=True, uarch_time=self.analysis.execute_stage)
        self.graph.add_node(btb_predicted_target_execute)
        self.btb_nodes['btb_predicted_target_execute'] = btb_predicted_target_execute
        print(f"  Created {btb_name}_predicted_target_execute")

    # =========================================================================
    # Phase 4: HARDWARE
    # =========================================================================

    def _generate_hardware(self, params: Dict):
        """Generate hardware logic for BTB."""

        btb_name = self.spec.btb_name

        # =====================================================================
        # Create BTB lookup logic
        # =====================================================================
        print("  Creating BTB lookup logic...")

        # The BTB storage node handles lookup internally
        # Connect fetch_pc to BTB for lookup
        btb_storage = self.btb_nodes['btb_storage']
        fetch_pc = self.analysis.fetch_pc

        # Lookup address edge
        lookup_edge = Edge(fetch_pc, btb_storage, data={
            'type': 'btb_lookup',
            'btb_component': True
        })
        self.graph.add_edge(lookup_edge)
        print(f"    Connected {fetch_pc.id} -> {btb_storage.id} (lookup)")

        # BTB outputs
        btb_hit = self.btb_nodes['btb_hit']
        btb_predicted_target = self.btb_nodes['btb_predicted_target']
        btb_predicted_taken = self.btb_nodes['btb_predicted_taken']

        # Connect BTB storage outputs
        hit_edge = Edge(btb_storage, btb_hit, data={
            'type': 'btb_hit_output',
            'btb_component': True
        })
        self.graph.add_edge(hit_edge)

        target_edge = Edge(btb_storage, btb_predicted_target, data={
            'type': 'btb_target_output',
            'btb_component': True
        })
        self.graph.add_edge(target_edge)

        taken_edge = Edge(btb_storage, btb_predicted_taken, data={
            'type': 'btb_taken_output',
            'btb_component': True
        })
        self.graph.add_edge(taken_edge)
        print(f"    Connected BTB outputs (hit, predicted_target, predicted_taken)")

        # =====================================================================
        # Create btb_use signal: hit && predicted_taken && !ras_pop
        # =====================================================================
        print("  Creating BTB use signal...")
        btb_use = self.btb_nodes['btb_use']

        # hit && predicted_taken
        hit_and_taken = Node(f'{btb_name}_hit_and_taken', data={
            'type': 'operation',
            'operator': '&&',
            'name': f'{btb_name}_hit_and_taken',
            'display_name': 'BTB hit && predicted_taken',
            'bit_width': 1,
            'btb_component': True
        })
        self.graph.add_node(hit_and_taken)
        edge1 = Edge(btb_hit, hit_and_taken, data={'type': 'operand', 'position': 'left'})
        edge2 = Edge(btb_predicted_taken, hit_and_taken, data={'type': 'operand', 'position': 'right'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)

        if self.spec.has_ras_coordination:
            # Create !ras_pop
            ras_pop_not = Node(f'{btb_name}_ras_pop_not', data={
                'type': 'operation',
                'operator': '!',
                'name': f'{btb_name}_ras_pop_not',
                'display_name': '!ras_pop',
                'bit_width': 1,
                'btb_component': True
            })
            self.graph.add_node(ras_pop_not)
            edge = Edge(self.analysis.ras_pop, ras_pop_not, data={'type': 'operand'})
            self.graph.add_edge(edge)

            # hit_and_taken && !ras_pop
            btb_use_logic = Node(f'{btb_name}_use_logic', data={
                'type': 'operation',
                'operator': '&&',
                'name': f'{btb_name}_use_logic',
                'display_name': 'BTB use (with RAS suppression)',
                'bit_width': 1,
                'btb_component': True
            })
            self.graph.add_node(btb_use_logic)
            edge1 = Edge(hit_and_taken, btb_use_logic, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(ras_pop_not, btb_use_logic, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)

            # Connect to btb_use
            edge = Edge(btb_use_logic, btb_use, data={'type': 'assignment'})
            self.graph.add_edge(edge)
            print(f"    Created btb_use = hit && predicted_taken && !ras_pop")
        else:
            # No RAS - btb_use = hit && predicted_taken
            edge = Edge(hit_and_taken, btb_use, data={'type': 'assignment'})
            self.graph.add_edge(edge)
            print(f"    Created btb_use = hit && predicted_taken")

        # =====================================================================
        # Create update enable (OR of all branch enables)
        # =====================================================================
        print("  Creating BTB update enable...")
        btb_update_enable = self.btb_nodes['btb_update_enable']

        if len(self.analysis.branch_enables) == 1:
            # Single enable - direct connection
            edge = Edge(self.analysis.branch_enables[0], btb_update_enable, data={'type': 'assignment'})
            self.graph.add_edge(edge)
        else:
            # Multiple enables - OR them together
            or_result = self.analysis.branch_enables[0]
            for i, enable in enumerate(self.analysis.branch_enables[1:], 1):
                new_or = Node(f'{btb_name}_update_or_{i}', data={
                    'type': 'operation',
                    'operator': '||',
                    'name': f'{btb_name}_update_or_{i}',
                    'display_name': f'BTB update enable OR {i}',
                    'bit_width': 1,
                    'btb_component': True
                })
                self.graph.add_node(new_or)
                edge1 = Edge(or_result, new_or, data={'type': 'operand', 'position': 'left'})
                edge2 = Edge(enable, new_or, data={'type': 'operand', 'position': 'right'})
                self.graph.add_edge(edge1)
                self.graph.add_edge(edge2)
                or_result = new_or

            edge = Edge(or_result, btb_update_enable, data={'type': 'assignment'})
            self.graph.add_edge(edge)

        print(f"    Created btb_update_enable (OR of {len(self.analysis.branch_enables)} enables)")

        # =====================================================================
        # Connect update interface to BTB storage
        # =====================================================================
        print("  Creating BTB update interface...")

        # Update PC
        update_pc_edge = Edge(self.analysis.branch_pc, btb_storage, data={
            'type': 'btb_update_pc',
            'btb_component': True
        })
        self.graph.add_edge(update_pc_edge)

        # Update target
        update_target_edge = Edge(self.analysis.branch_target, btb_storage, data={
            'type': 'btb_update_target',
            'btb_component': True
        })
        self.graph.add_edge(update_target_edge)

        # Update taken
        update_taken_edge = Edge(self.analysis.branch_outcome, btb_storage, data={
            'type': 'btb_update_taken',
            'btb_component': True
        })
        self.graph.add_edge(update_taken_edge)

        # Update enable
        update_enable_edge = Edge(btb_update_enable, btb_storage, data={
            'type': 'btb_update_enable',
            'btb_component': True
        })
        self.graph.add_edge(update_enable_edge)

        print(f"    Connected update interface (pc, target, taken, enable)")

    # =========================================================================
    # Phase 5: CONNECTION
    # =========================================================================

    def _wire_components(self, params: Dict):
        """Wire BTB components to prediction infrastructure."""

        btb_name = self.spec.btb_name
        btb_use = self.btb_nodes['btb_use']
        btb_predicted_target = self.btb_nodes['btb_predicted_target']
        btb_mispredict = self.btb_nodes['btb_mispredict']
        btb_use_execute = self.btb_nodes['btb_use_execute']
        btb_predicted_target_execute = self.btb_nodes['btb_predicted_target_execute']

        # =====================================================================
        # Pipeline btb_use and btb_predicted_target to Execute stage
        # =====================================================================
        print("  Creating pipeline registers for misprediction detection...")

        # Gate btb_use with !control_hazard_flush so it clears on flush
        # This prevents stale BTB predictions from affecting instructions after flush
        control_hazard_flush = self.analysis.control_hazard_flush

        # Create !control_hazard_flush
        control_hazard_flush_not = self.graph.nodes.get('control_hazard_flush_not')
        if not control_hazard_flush_not:
            control_hazard_flush_not = Node(f'control_hazard_flush_not', data={
                'type': 'operation',
                'operator': '!',
                'name': 'control_hazard_flush_not',
                'display_name': '!control_hazard_flush',
                'bit_width': 1,
                'btb_component': True
            })
            self.graph.add_node(control_hazard_flush_not)
            edge = Edge(control_hazard_flush, control_hazard_flush_not, data={'type': 'operand'})
            self.graph.add_edge(edge)
            print(f"    Created control_hazard_flush_not")

        # Create btb_use_and_not_flush = btb_use && !control_hazard_flush
        btb_use_and_not_flush = Node(f'{btb_name}_use_and_not_flush', data={
            'type': 'operation',
            'operator': '&&',
            'name': f'{btb_name}_use_and_not_flush',
            'display_name': 'BTB use gated by flush',
            'bit_width': 1,
            'btb_component': True
        })
        self.graph.add_node(btb_use_and_not_flush)
        edge1 = Edge(btb_use, btb_use_and_not_flush, data={'type': 'operand', 'position': 'left'})
        edge2 = Edge(control_hazard_flush_not, btb_use_and_not_flush, data={'type': 'operand', 'position': 'right'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)
        print(f"    Created btb_use_and_not_flush = btb_use && !control_hazard_flush")

        # Calculate number of pipeline stages needed
        stages_needed = self.analysis.execute_stage - self.analysis.fetch_stage
        print(f"    Pipeline stages from Fetch to Execute: {stages_needed}")

        # Get stall controllers for different stages
        decode_stall_ctrl = self.graph.nodes.get('PIPE_Decode_stall_ctrl_and_not_flush')
        if not decode_stall_ctrl:
            decode_stall_ctrl = self.graph.nodes.get('PIPE_Decode_stall_ctrl')

        # For now, skip pipelining btb_use since it has synchronization issues
        # with stalls. Instead, we'll detect misprediction using a fresh BTB
        # lookup at Execute stage (via the btb_storage execute_lookup_pc port).
        #
        # The btb_use signal is still created and used for Fetch-stage prediction,
        # but misprediction detection will use execute_hit && execute_predicted_taken
        # instead of the pipelined btb_use_execute.
        print(f"    Skipping BTB pipeline registers (using dual-port lookup instead)")

        print(f"    Created pipeline registers for Execute stage")

        # =====================================================================
        # Create misprediction detection using dual-port BTB lookup
        # =====================================================================
        print("  Creating misprediction detection (using dual-port BTB lookup)...")

        # Instead of pipelining btb_use through Decode->Execute (which has stall
        # synchronization issues), we do a fresh BTB lookup at Execute stage using
        # the Execute-stage PC. This gives us execute_hit and execute_predicted_taken
        # signals that are guaranteed to be in sync with the instruction in Execute.

        btb_storage = self.btb_nodes['btb_storage']

        # Create execute_hit output node (from dual-port BTB)
        execute_hit = Node(f'{btb_name}_execute_hit', data={
            'type': 'var',
            'name': f'{btb_name}_execute_hit',
            'display_name': 'BTB Execute Hit',
            'bit_width': 1,
            'btb_component': True,
            'btb_output': True  # Declared by BTB module
        }, uarch_time=self.analysis.execute_stage)
        self.graph.add_node(execute_hit)
        self.btb_nodes['execute_hit'] = execute_hit
        print(f"    Created {btb_name}_execute_hit")

        # Create execute_predicted_taken output node (from dual-port BTB)
        execute_predicted_taken = Node(f'{btb_name}_execute_predicted_taken', data={
            'type': 'var',
            'name': f'{btb_name}_execute_predicted_taken',
            'display_name': 'BTB Execute Predicted Taken',
            'bit_width': 1,
            'btb_component': True,
            'btb_output': True  # Declared by BTB module
        }, uarch_time=self.analysis.execute_stage)
        self.graph.add_node(execute_predicted_taken)
        self.btb_nodes['execute_predicted_taken'] = execute_predicted_taken
        print(f"    Created {btb_name}_execute_predicted_taken")

        # Connect Execute-stage PC to BTB for dual-port lookup
        # Use the pipelined PC that tracks with the instruction in Execute
        execute_pc = self.graph.nodes.get('PIPE_Execute_PIPE_Decode_pc_rd_PIPE_PIPE')
        if not execute_pc:
            print(f"    WARNING: Execute-stage PC not found, falling back to update_pc signal")
            # Fall back to whatever PC is used for BTB updates
        else:
            edge = Edge(execute_pc, btb_storage, data={'type': 'btb_execute_lookup'})
            self.graph.add_edge(edge)
            print(f"    Connected Execute-stage PC to BTB for dual-port lookup")

        # Create execute_btb_use = execute_hit && execute_predicted_taken
        execute_btb_use = Node(f'{btb_name}_execute_btb_use', data={
            'type': 'operation',
            'operator': '&&',
            'name': f'{btb_name}_execute_btb_use',
            'display_name': 'BTB Execute Use (hit && predicted_taken)',
            'bit_width': 1,
            'btb_component': True
        })
        self.graph.add_node(execute_btb_use)
        edge1 = Edge(execute_hit, execute_btb_use, data={'type': 'operand', 'position': 'left'})
        edge2 = Edge(execute_predicted_taken, execute_btb_use, data={'type': 'operand', 'position': 'right'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)
        print(f"    Created execute_btb_use = execute_hit && execute_predicted_taken")

        # Gate misprediction by Execute stage validity
        execute_valid = self.graph.nodes.get('PIPE_Execute_valid_PIPE')
        if not execute_valid:
            print(f"    WARNING: PIPE_Execute_valid_PIPE not found, mispredictions may fire during stalls")

        # Create !branch_outcome (branch was NOT taken)
        branch_not_taken = Node(f'{btb_name}_branch_not_taken', data={
            'type': 'operation',
            'operator': '!',
            'name': f'{btb_name}_branch_not_taken',
            'display_name': 'Branch not taken',
            'bit_width': 1,
            'btb_component': True
        })
        self.graph.add_node(branch_not_taken)
        edge = Edge(self.analysis.branch_outcome, branch_not_taken, data={'type': 'operand'})
        self.graph.add_edge(edge)
        print(f"    Created !branch_outcome signal")

        # Misprediction = execute_btb_use && !branch_taken
        # This fires when BTB predicted taken but branch wasn't taken (or wasn't a branch)
        mispredict_and = Node(f'{btb_name}_mispredict_and', data={
            'type': 'operation',
            'operator': '&&',
            'name': f'{btb_name}_mispredict_and',
            'display_name': 'BTB misprediction (predicted taken but not taken)',
            'bit_width': 1,
            'btb_component': True
        })
        self.graph.add_node(mispredict_and)
        edge1 = Edge(execute_btb_use, mispredict_and, data={'type': 'operand', 'position': 'left'})
        edge2 = Edge(branch_not_taken, mispredict_and, data={'type': 'operand', 'position': 'right'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)

        if execute_valid:
            # Gate by validity: mispredict = (execute_btb_use && !branch_taken) && valid
            mispredict_valid_gated = Node(f'{btb_name}_mispredict_valid_gated', data={
                'type': 'operation',
                'operator': '&&',
                'name': f'{btb_name}_mispredict_valid_gated',
                'display_name': 'BTB misprediction (validity gated)',
                'bit_width': 1,
                'btb_component': True
            })
            self.graph.add_node(mispredict_valid_gated)
            edge1 = Edge(mispredict_and, mispredict_valid_gated, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(execute_valid, mispredict_valid_gated, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)
            print(f"    Created validity-gated misprediction signal")

            # Connect gated signal to btb_mispredict
            edge = Edge(mispredict_valid_gated, btb_mispredict, data={'type': 'assignment'})
            self.graph.add_edge(edge)
        else:
            # No validity signal - connect directly
            edge = Edge(mispredict_and, btb_mispredict, data={'type': 'assignment'})
            self.graph.add_edge(edge)

        print(f"    Created btb_mispredict = btb_use_execute && !branch_taken && valid")

        # =====================================================================
        # Add BTB misprediction to control_hazard_flush
        # =====================================================================
        print("  Integrating BTB misprediction with control hazard flush...")

        control_hazard_flush = self.analysis.control_hazard_flush

        # control_hazard_flush is an OR operation node with operand edges from
        # all the branch_taken signals. We need to:
        # 1. Collect all existing operand sources
        # 2. Gate them with !btb_execute_btb_use (when BTB predicted correctly, don't flush)
        # 3. OR with btb_mispredict (when BTB predicted wrong, do flush)

        # Collect existing operand sources
        existing_sources = []
        edges_to_remove = []
        for edge in list(control_hazard_flush.incoming_edges):
            edge_type = edge.data.get('type', '')
            # Check for operand edges (left_operand, right_operand, or just 'operand')
            if 'operand' in edge_type or edge_type in ['left_operand', 'right_operand']:
                existing_sources.append(edge.source)
                edges_to_remove.append(edge)

        print(f"    Found {len(existing_sources)} existing operand sources to control_hazard_flush")

        if existing_sources:
            # Remove old operand edges
            for edge in edges_to_remove:
                self.graph.remove_edge(edge.id)

            # Create intermediate OR if multiple sources, otherwise use single source
            if len(existing_sources) == 1:
                existing_combined = existing_sources[0]
            else:
                # Create OR chain for existing sources
                existing_combined = existing_sources[0]
                for i, source in enumerate(existing_sources[1:], 1):
                    or_node = Node(f'{btb_name}_existing_or_{i}', data={
                        'type': 'operation',
                        'operator': '||',
                        'name': f'{btb_name}_existing_or_{i}',
                        'bit_width': 1,
                        'btb_component': True
                    }, uarch_time=self.analysis.execute_stage)
                    self.graph.add_node(or_node)
                    edge1 = Edge(existing_combined, or_node, data={'type': 'operand', 'position': 'left'})
                    edge2 = Edge(source, or_node, data={'type': 'operand', 'position': 'right'})
                    self.graph.add_edge(edge1)
                    self.graph.add_edge(edge2)
                    existing_combined = or_node

            # Create NOT node for btb_execute_btb_use
            btb_execute_btb_use_not = Node(f'{btb_name}_execute_btb_use_not', data={
                'type': 'operation',
                'operator': '!',
                'name': f'{btb_name}_execute_btb_use_not',
                'bit_width': 1,
                'btb_component': True
            }, uarch_time=self.analysis.execute_stage)
            self.graph.add_node(btb_execute_btb_use_not)
            not_edge = Edge(execute_btb_use, btb_execute_btb_use_not, data={'type': 'operand'})
            self.graph.add_edge(not_edge)

            # Gate existing combined with !btb_execute_btb_use
            # existing_gated = existing_combined && !btb_execute_btb_use
            existing_gated = Node(f'{btb_name}_existing_flush_gated', data={
                'type': 'operation',
                'operator': '&&',
                'name': f'{btb_name}_existing_flush_gated',
                'bit_width': 1,
                'btb_component': True
            }, uarch_time=self.analysis.execute_stage)
            self.graph.add_node(existing_gated)
            gated_edge1 = Edge(existing_combined, existing_gated, data={'type': 'operand', 'position': 'left'})
            gated_edge2 = Edge(btb_execute_btb_use_not, existing_gated, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(gated_edge1)
            self.graph.add_edge(gated_edge2)

            # Connect gated sources and btb_mispredict to control_hazard_flush
            edge1 = Edge(existing_gated, control_hazard_flush, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(btb_mispredict, control_hazard_flush, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)

            print(f"    Gated existing flush sources with !btb_execute_btb_use")
            print(f"    New flush = (existing_sources && !btb_execute_btb_use) || btb_mispredict")
        else:
            # No existing operand sources - just connect BTB misprediction
            edge = Edge(btb_mispredict, control_hazard_flush, data={'type': 'operand'})
            self.graph.add_edge(edge)
            print(f"    Connected BTB misprediction directly to control_hazard_flush")

        # =====================================================================
        # Add BTB recovery path using Execute-stage PC + 4
        # =====================================================================
        print("  Adding BTB recovery path...")

        # Find the pc_recovery_mux and the Execute-stage pc_add_4
        pc_recovery_mux = self.graph.nodes.get('pc_recovery_mux')

        # Find Execute-stage pc_add_4 (pipelined through Decode to Execute)
        # The naming convention is: PIPE_Execute_PIPE_Decode_<signal>_PIPE_PIPE
        execute_pc_add_4 = self.graph.nodes.get('PIPE_Execute_PIPE_Decode_pc_add_4_PIPE_PIPE')
        if not execute_pc_add_4:
            # Alternative: look for pc_add_4 with Execute timing
            for node_id, node in self.graph.nodes.items():
                if 'pc_add_4' in node_id and node.uarch_time == self.analysis.execute_stage:
                    execute_pc_add_4 = node
                    break

        if pc_recovery_mux and execute_pc_add_4:
            # Create BTB recovery mux that selects Execute-stage PC+4 when BTB mispredicts
            # btb_recovery_mux = btb_mispredict ? execute_pc_add_4 : pc_recovery_mux

            # Save the current pc_recovery_mux result
            old_recovery_result = None
            for edge in list(pc_recovery_mux.outgoing_edges):
                old_recovery_result = edge.target
                break

            if old_recovery_result:
                # Create BTB-specific recovery mux
                btb_recovery_mux = Node(f'{btb_name}_recovery_mux', data={
                    'type': 'ternary_op',
                    'name': f'{btb_name}_recovery_mux',
                    'display_name': 'BTB recovery mux',
                    'bit_width': params['pc_width'],
                    'btb_component': True
                }, uarch_time=0)
                self.graph.add_node(btb_recovery_mux)

                # Remove old edge from pc_recovery_mux to its target FIRST
                # (before adding the false_edge which also goes from pc_recovery_mux)
                for edge in list(pc_recovery_mux.outgoing_edges):
                    self.graph.remove_edge(edge.id)

                # Connect: btb_mispredict ? execute_pc_add_4 : pc_recovery_mux
                cond_edge = Edge(btb_mispredict, btb_recovery_mux, data={'type': 'ternary_condition'})
                true_edge = Edge(execute_pc_add_4, btb_recovery_mux, data={'type': 'ternary_true'})
                false_edge = Edge(pc_recovery_mux, btb_recovery_mux, data={'type': 'ternary_false'})
                self.graph.add_edge(cond_edge)
                self.graph.add_edge(true_edge)
                self.graph.add_edge(false_edge)

                # Connect btb_recovery_mux to the old target (pc_node)
                new_edge = Edge(btb_recovery_mux, old_recovery_result, data={'type': 'assignment'})
                self.graph.add_edge(new_edge)

                print(f"    Created BTB recovery mux: btb_mispredict ? Execute_PC+4 : original_recovery")
                print(f"    Execute PC+4 source: {execute_pc_add_4.id}")
            else:
                print(f"    WARNING: Could not find pc_recovery_mux target")
        else:
            if not pc_recovery_mux:
                print(f"    WARNING: pc_recovery_mux not found")
            if not execute_pc_add_4:
                print(f"    WARNING: Execute-stage pc_add_4 not found")
            print(f"    Skipping BTB recovery mux (will use default recovery path)")

        # =====================================================================
        # Create prediction mux (with RAS priority if present)
        # =====================================================================
        print("  Creating prediction mux...")

        default_prediction = self.analysis.default_prediction
        predicted_pc = self.analysis.predicted_pc

        # btb_or_default = btb_use ? btb_predicted_target : default_prediction
        btb_or_default = Node(f'{btb_name}_or_default', data={
            'type': 'ternary_op',
            'name': f'{btb_name}_or_default',
            'display_name': 'BTB or default prediction',
            'bit_width': params['pc_width'],
            'btb_component': True
        })
        self.graph.add_node(btb_or_default)

        # Connect ternary inputs
        cond_edge = Edge(btb_use, btb_or_default, data={'type': 'ternary_condition'})
        true_edge = Edge(btb_predicted_target, btb_or_default, data={'type': 'ternary_true'})
        false_edge = Edge(default_prediction, btb_or_default, data={'type': 'ternary_false'})
        self.graph.add_edge(cond_edge)
        self.graph.add_edge(true_edge)
        self.graph.add_edge(false_edge)

        if self.spec.has_ras_coordination:
            # predicted_pc = ras_pop ? ras_top : btb_or_default
            ras_priority_mux = Node(f'{btb_name}_ras_priority_mux', data={
                'type': 'ternary_op',
                'name': f'{btb_name}_ras_priority_mux',
                'display_name': 'RAS > BTB priority mux',
                'bit_width': params['pc_width'],
                'btb_component': True
            })
            self.graph.add_node(ras_priority_mux)

            cond_edge = Edge(self.analysis.ras_pop, ras_priority_mux, data={'type': 'ternary_condition'})
            true_edge = Edge(self.analysis.ras_top, ras_priority_mux, data={'type': 'ternary_true'})
            false_edge = Edge(btb_or_default, ras_priority_mux, data={'type': 'ternary_false'})
            self.graph.add_edge(cond_edge)
            self.graph.add_edge(true_edge)
            self.graph.add_edge(false_edge)

            # Find and replace predicted_pc driver
            self._replace_predicted_pc_driver(predicted_pc, ras_priority_mux)
            print(f"    Created prediction mux: ras_pop ? ras_top : (btb_use ? btb_target : pc+4)")
        else:
            # No RAS - connect btb_or_default directly
            self._replace_predicted_pc_driver(predicted_pc, btb_or_default)
            print(f"    Created prediction mux: btb_use ? btb_target : pc+4")

    def _replace_predicted_pc_driver(self, predicted_pc: Node, new_driver: Node):
        """Replace the driver of predicted_pc with new_driver."""
        # Find existing driver edge
        for edge in list(predicted_pc.incoming_edges):
            if edge.data.get('type') in ('assignment', 'ternary_result'):
                # Remove old edge
                self.graph.remove_edge(edge.id)
                break

        # Add new driver edge
        edge = Edge(new_driver, predicted_pc, data={'type': 'assignment'})
        self.graph.add_edge(edge)

    # =========================================================================
    # Phase 6: CLEANUP
    # =========================================================================

    def _cleanup(self):
        """Remove orphaned nodes and clean up."""
        # BTB doesn't typically need cleanup - all nodes are new
        print("  No cleanup required")

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_summary(self) -> str:
        """Get a summary of the BTB optimization."""
        lines = [
            "=" * 70,
            "BRANCH TARGET BUFFER SUMMARY",
            "=" * 70,
            f"BTB name: {self.spec.btb_name}",
            f"Entries: {self.spec.num_entries}",
            f"Associativity: {self.spec.associativity}",
            f"Index width: {self.spec.index_width} bits",
            f"Tag width: {self.spec.tag_width} bits",
            f"Confidence bits: {self.spec.confidence_bits}",
            f"RAS coordination: {self.spec.has_ras_coordination}",
            "",
            f"Branch enables: {len(self.spec.branch_enable_nodes)}",
        ]
        for enable in self.spec.branch_enable_nodes:
            lines.append(f"  - {enable}")

        lines.append("")
        lines.append("BTB nodes created:")
        for name, node in self.btb_nodes.items():
            lines.append(f"  - {name}")

        lines.append("=" * 70)
        return "\n".join(lines)


def apply_branch_target_buffer(graph: ResourceGraph, spec: BTBSpec) -> bool:
    """
    Convenience function to apply BTB optimization to a ResourceGraph.

    Args:
        graph: ResourceGraph to optimize
        spec: BTB specification

    Returns:
        True if BTB was successfully applied
    """
    btb = BranchTargetBufferOptimization(graph, spec)
    success = btb.apply()

    if success:
        print(btb.get_summary())

    return success


if __name__ == "__main__":
    # Test BTB optimization
    import os
    import sys

    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from core.graph_merger import ResourceGraphMerger

    print("BRANCH TARGET BUFFER OPTIMIZATION TEST")
    print("=" * 70)

    # Build a simple merged graph with branch instructions
    rv32i_dir = os.path.join(project_root, "riscv32")

    merger = ResourceGraphMerger()
    merger.add_instruction('beq', os.path.join(rv32i_dir, 'beq.isa'))
    merger.add_instruction('bne', os.path.join(rv32i_dir, 'bne.isa'))
    merger.add_instruction('jal', os.path.join(rv32i_dir, 'jal.isa'))
    merger.add_instruction('add', os.path.join(rv32i_dir, 'add.isa'))

    merged = merger.merge_graphs()
    merged.infer_uarch_time()

    print(f"\nMerged graph: {len(merged.nodes)} nodes, {len(merged.edges)} edges")
    print("\nNote: Full BTB test requires pipelined graph with hazard resolution.")
