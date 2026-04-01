#!/usr/bin/env python3
"""
Return Address Stack (RAS) Optimization for ResourceGraph.

This module implements a Return Address Stack optimization that predicts return
addresses by maintaining a stack of call return addresses. This significantly
improves branch prediction accuracy for subroutine call/return patterns.

Key features:
- Pushes return address (PC+4) onto stack when a call instruction is detected
- Pops and provides predicted target address when a return instruction is detected
- Integrates with existing branch prediction and control hazard infrastructure
- Configurable stack depth and link register conventions

This follows the 7-phase optimization pattern:
1. ANALYSIS - Validate inputs and understand graph structure
2. PLANNING - Create specifications for hardware components
3. STRUCTURE - Build skeleton nodes for RAS components
4. HARDWARE - Generate comparators, logic gates, stack logic
5. CONNECTION - Wire all components together
6. CLEANUP - Remove orphaned nodes
7. TIMING - Re-infer timing information
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
import math

from core.resource_graph import ResourceGraph, Node, Edge
from core.hardware_builders import HardwareBuilderFactory


@dataclass
class CallSpec:
    """Specification for a call instruction pattern."""
    enable_node_id: str          # e.g., 'jal_enable' - instruction enable signal
    dest_reg_node_id: str        # e.g., 'rd' - destination register number node
    return_addr_node_id: str     # e.g., 'ret_addr' - return address value (PC+4)


@dataclass
class ReturnSpec:
    """Specification for a return instruction pattern."""
    enable_node_id: str          # e.g., 'jalr_enable' - instruction enable signal
    src_reg_node_id: str         # e.g., 'rs1' - source register number node
    dest_reg_node_id: str        # e.g., 'rd' - destination register (must be 0 for return)


@dataclass
class RASSpec:
    """Specification for Return Address Stack optimization."""

    # Call patterns (push RAS when enable && dest_reg is link register)
    call_specs: List[CallSpec]

    # Return patterns (pop RAS when enable && src_reg is link register && dest_reg == 0)
    return_specs: List[ReturnSpec]

    # Link register configuration - which register numbers indicate call/return
    link_registers: List[int] = field(default_factory=lambda: [1, 5])  # x1(ra), x5(t0)

    # RAS configuration
    ras_depth: int = 8           # Number of stack entries (power of 2)
    ras_width: int = 32          # Address width

    # Required: PC prediction infrastructure nodes (must exist in graph)
    predicted_pc_node_id: str = None         # Node that holds the predicted next PC
    default_prediction_node_id: str = None   # Node that holds PC+4 (default prediction)

    # Required: Control hazard infrastructure
    control_hazard_flush_node_id: str = None  # The control hazard flush signal

    # Required: JALR target for misprediction detection
    jalr_target_node_id: str = None           # The computed JALR target (for comparison)

    # Optional: Execute-stage JALR enable for misprediction detection (pipelined)
    # This is the Execute-stage pipelined version of jalr_enable
    # If not provided, a pipelined version of ras_pop will be created
    jalr_execute_enable_node_id: str = None

    # Optional: Return branch taken signal for conditional returns (e.g., OpenPOWER bclr)
    # For unconditional returns (RISC-V jalr, MIPS jr), leave as None.
    # For conditional returns, this should be the Execute-stage signal that indicates
    # whether the return branch was actually taken (e.g., 'bclr_branch_taken_execute').
    # Misprediction logic becomes: ras_pop_execute && (!branch_taken || prediction_mismatch)
    return_branch_taken_node_id: str = None

    # Use combinational (not registered) validity gating on RAS operations.
    # Set to True for architectures WITHOUT delay slots (like OpenPOWER) where
    # there's no concern about stale instructions from before a flush. The
    # combinational signal (PIPE_Decode_valid_not_flush) gates properly without
    # the one-cycle delay that blocks valid instructions after a branch.
    # Set to False (default) for architectures WITH delay slots (like MIPS32) where
    # stale instructions can enter the pipeline after a flush and need the
    # registered validity signal (PIPE_Decode_valid_PIPE) to block them.
    use_combinational_validity: bool = False


@dataclass
class RASAnalysis:
    """Results from analyzing the graph for RAS applicability."""
    # Validated call specs with resolved nodes
    call_nodes: List[Dict]  # [{enable: Node, dest_reg: Node, return_addr: Node}, ...]

    # Validated return specs with resolved nodes
    return_nodes: List[Dict]  # [{enable: Node, src_reg: Node, dest_reg: Node}, ...]

    # Required infrastructure nodes (validated from spec)
    predicted_pc: Node = None           # The predicted PC node
    default_prediction: Node = None     # The PC+4 node (default prediction)
    control_hazard_flush: Node = None   # The control hazard flush signal
    jalr_target: Node = None            # The JALR computed target
    jalr_execute_enable: Node = None    # Optional: Execute-stage JALR enable
    return_branch_taken: Node = None    # Optional: For conditional returns (OpenPOWER bclr)

    # Timing info
    decode_stage: int = 0  # Pipeline stage where call/return is detected


class RASOptimization:
    """
    Implements Return Address Stack optimization.

    The RAS predicts return addresses by maintaining a stack that is:
    - Pushed when a call instruction is executed (writes to link register)
    - Popped when a return instruction is executed (reads from link register with rd=0)
    """

    def __init__(self, graph: ResourceGraph, spec: RASSpec):
        self.graph = graph
        self.spec = spec
        self.hw_factory = HardwareBuilderFactory(graph)
        self.analysis: Optional[RASAnalysis] = None

        # Created nodes for later reference
        self.ras_nodes: Dict[str, Node] = {}

    def _find_stall_controller_for_stage(self, source_node_id: str) -> Optional[Node]:
        """
        Find the stall controller that gates the transition FROM the stage where
        source_node_id lives TO the next stage.

        This is a purely structural approach:
        1. Find the source node and its uarch_time (the RAS source stage)
        2. Find pipeline registers that capture data from that stage
           (they have pipeline_input edges from nodes at the same uarch_time)
        3. Find the stall controller that gates those registers
        4. Among multiple controllers, pick the one at the earliest stage
           (this is the one that controls the source→next transition,
           not downstream stall propagation)

        Args:
            source_node_id: A node ID at the source stage (e.g., 'jalr_enable')

        Returns:
            The stall controller node, or None if not found.
        """
        # Step 1: Find the source node and its stage (uarch_time)
        if source_node_id not in self.graph.nodes:
            print(f"    [DEBUG] Source node '{source_node_id}' not found")
            return None

        source_node = self.graph.nodes[source_node_id]
        source_time = source_node.uarch_time
        if source_time is None:
            print(f"    [DEBUG] Source node '{source_node_id}' has no uarch_time")
            return None

        print(f"    [DEBUG] Source node '{source_node_id}' is at uarch_time {source_time}")

        # Step 2: Find pipeline registers that capture data from the source stage
        # These registers have:
        # - type == 'pipeline_register'
        # - A pipeline_input edge from a node at the same uarch_time as source_node
        candidate_registers = []

        for node in self.graph.nodes.values():
            if node.data.get('type') != 'pipeline_register':
                continue

            # Check if this register receives pipeline_input from source stage
            for edge in node.incoming_edges:
                if edge.data.get('type') == 'pipeline_input':
                    input_source = edge.source
                    input_time = input_source.uarch_time
                    if input_time == source_time:
                        candidate_registers.append((node, input_source))
                        break

        if not candidate_registers:
            print(f"    [DEBUG] No pipeline registers found capturing data from stage {source_time}")
            return None

        print(f"    [DEBUG] Found {len(candidate_registers)} pipeline registers capturing from stage {source_time}")

        # Step 3: Find stall controllers for these registers
        # Group by controller and track each controller's uarch_time
        controller_info = {}  # ctrl_id -> (ctrl_node, min_uarch_time, count)

        for reg_node, _ in candidate_registers:
            for edge in reg_node.incoming_edges:
                if edge.data.get('type') == 'stall':
                    ctrl = edge.source
                    ctrl_id = ctrl.id
                    ctrl_time = ctrl.uarch_time if ctrl.uarch_time is not None else float('inf')

                    if ctrl_id not in controller_info:
                        controller_info[ctrl_id] = [ctrl, ctrl_time, 0]

                    # Track the earliest time we see for this controller
                    if ctrl_time < controller_info[ctrl_id][1]:
                        controller_info[ctrl_id][1] = ctrl_time
                    controller_info[ctrl_id][2] += 1

        if not controller_info:
            print(f"    [DEBUG] No stall controllers found for pipeline registers")
            return None

        print(f"    [DEBUG] Found {len(controller_info)} stall controllers:")
        for ctrl_id, (ctrl, ctrl_time, count) in sorted(controller_info.items(), key=lambda x: x[1][1]):
            print(f"      - {ctrl_id}: uarch_time={ctrl_time}, {count} uses")

        # Step 4: Select the appropriate controller
        # Multiple controllers may gate the same registers due to stall propagation.
        # We want the controller for the source stage transition, not downstream stalls.
        #
        # Selection criteria (in order of priority):
        # 1. Prefer controllers with stall_type='hazard_detection' (these are stage-specific)
        # 2. Exclude controllers with 'memory' attribute (these are memory-latency specific)
        # 3. Among remaining, prefer _and_not_flush variant
        # 4. Fall back to most used controller

        hazard_controllers = []
        non_memory_controllers = []

        for ctrl_id, (ctrl, ctrl_time, count) in controller_info.items():
            ctrl_data = ctrl.data or {}

            # For _and_not_flush variants, look at the base controller's attributes
            # The base controller has the semantic information (stage, memory, stall_type)
            base_ctrl_id = ctrl_id.replace('_and_not_flush', '').replace('_not', '')
            base_ctrl = self.graph.nodes.get(base_ctrl_id)
            base_data = base_ctrl.data if base_ctrl else ctrl_data

            stall_type = base_data.get('stall_type', '')
            has_memory = 'memory' in base_data

            if stall_type == 'hazard_detection':
                hazard_controllers.append((ctrl_id, ctrl, count))
            elif not has_memory:
                non_memory_controllers.append((ctrl_id, ctrl, count))

        # Try hazard_detection controllers first
        if hazard_controllers:
            hazard_controllers.sort(key=lambda x: -x[2])  # Sort by usage count
            print(f"    [DEBUG] Found {len(hazard_controllers)} hazard_detection controllers")
            for ctrl_id, ctrl, _ in hazard_controllers:
                if '_and_not_flush' in ctrl_id:
                    print(f"    [DEBUG] Selected controller: {ctrl_id} (hazard_detection with _and_not_flush)")
                    return ctrl
            selected_id, selected_ctrl, _ = hazard_controllers[0]
            print(f"    [DEBUG] Selected controller: {selected_id} (hazard_detection)")
            return selected_ctrl

        # Try non-memory controllers
        if non_memory_controllers:
            non_memory_controllers.sort(key=lambda x: -x[2])
            print(f"    [DEBUG] Found {len(non_memory_controllers)} non-memory controllers")
            for ctrl_id, ctrl, _ in non_memory_controllers:
                if '_and_not_flush' in ctrl_id:
                    print(f"    [DEBUG] Selected controller: {ctrl_id} (non-memory with _and_not_flush)")
                    return ctrl
            selected_id, selected_ctrl, _ = non_memory_controllers[0]
            print(f"    [DEBUG] Selected controller: {selected_id} (non-memory)")
            return selected_ctrl

        # Fall back to most-used controller
        sorted_controllers = sorted(
            controller_info.items(),
            key=lambda x: -x[1][2]  # Sort by count descending
        )
        for ctrl_id, (ctrl, _, _) in sorted_controllers:
            if '_and_not_flush' in ctrl_id:
                print(f"    [DEBUG] Selected controller: {ctrl_id} (fallback with _and_not_flush)")
                return ctrl

        selected_id, (selected_ctrl, _, _) = sorted_controllers[0]
        print(f"    [DEBUG] Selected controller: {selected_id} (fallback)")
        return selected_ctrl

    def apply(self) -> bool:
        """
        Apply RAS optimization to the graph.

        Returns:
            True if RAS was successfully applied
        """
        print("\n" + "=" * 70)
        print("APPLYING RETURN ADDRESS STACK (RAS) OPTIMIZATION")
        print("=" * 70)

        # Phase 1: ANALYSIS
        print("\n--- Phase 1: ANALYSIS ---")
        self.analysis = self._analyze()
        if self.analysis is None:
            print("Analysis failed - RAS optimization not applicable")
            return False

        # Phase 2: PLANNING
        print("\n--- Phase 2: PLANNING ---")
        self._plan()

        # Phase 3: STRUCTURE
        print("\n--- Phase 3: STRUCTURE ---")
        self._create_structure()

        # Phase 4: HARDWARE
        print("\n--- Phase 4: HARDWARE ---")
        self._generate_hardware()

        # Phase 5: CONNECTION
        print("\n--- Phase 5: CONNECTION ---")
        self._wire_components()

        # Phase 6: CLEANUP
        print("\n--- Phase 6: CLEANUP ---")
        self._cleanup_graph()

        # Phase 7: TIMING
        print("\n--- Phase 7: TIMING ---")
        self.graph.infer_uarch_time(force_reinfer=True)

        print("\n" + "=" * 70)
        print("RAS OPTIMIZATION COMPLETED SUCCESSFULLY")
        print("=" * 70)
        return True

    # =========================================================================
    # Phase 1: ANALYSIS
    # =========================================================================

    def _analyze(self) -> Optional[RASAnalysis]:
        """Analyze graph structure and validate RAS applicability."""

        call_nodes = []
        return_nodes = []

        # Validate call specifications
        print("  Validating call specifications...")
        for i, call_spec in enumerate(self.spec.call_specs):
            enable = self.graph.nodes.get(call_spec.enable_node_id)
            # dest_reg can be None for instructions that always link (e.g., MIPS JAL)
            dest_reg = None
            if call_spec.dest_reg_node_id is not None:
                dest_reg = self.graph.nodes.get(call_spec.dest_reg_node_id)
            return_addr = self.graph.nodes.get(call_spec.return_addr_node_id)

            if not enable:
                print(f"    Warning: Call enable node '{call_spec.enable_node_id}' not found")
                continue
            if call_spec.dest_reg_node_id is not None and not dest_reg:
                print(f"    Warning: Call dest_reg node '{call_spec.dest_reg_node_id}' not found")
                continue
            if not return_addr:
                print(f"    Warning: Call return_addr node '{call_spec.return_addr_node_id}' not found")
                continue

            call_nodes.append({
                'enable': enable,
                'dest_reg': dest_reg,  # Can be None for "always call" instructions
                'return_addr': return_addr,
                'spec': call_spec
            })
            if dest_reg:
                print(f"    Call pattern {i}: {call_spec.enable_node_id} -> push when dest_reg is link")
            else:
                print(f"    Call pattern {i}: {call_spec.enable_node_id} -> always push (unconditional call)")

        # Validate return specifications
        print("  Validating return specifications...")
        for i, return_spec in enumerate(self.spec.return_specs):
            enable = self.graph.nodes.get(return_spec.enable_node_id)
            # src_reg can be None for instructions that always read from link register
            src_reg = None
            if return_spec.src_reg_node_id is not None:
                src_reg = self.graph.nodes.get(return_spec.src_reg_node_id)
            # dest_reg can be None for instructions with no link option (e.g., MIPS JR)
            dest_reg = None
            if return_spec.dest_reg_node_id is not None:
                dest_reg = self.graph.nodes.get(return_spec.dest_reg_node_id)

            if not enable:
                print(f"    Warning: Return enable node '{return_spec.enable_node_id}' not found")
                continue
            if return_spec.src_reg_node_id is not None and not src_reg:
                print(f"    Warning: Return src_reg node '{return_spec.src_reg_node_id}' not found")
                continue
            if return_spec.dest_reg_node_id is not None and not dest_reg:
                print(f"    Warning: Return dest_reg node '{return_spec.dest_reg_node_id}' not found")
                continue

            return_nodes.append({
                'enable': enable,
                'src_reg': src_reg,   # Can be None for "always from LR" returns
                'dest_reg': dest_reg,  # Can be None for returns that never link
                'spec': return_spec
            })
            if src_reg and dest_reg:
                print(f"    Return pattern {i}: {return_spec.enable_node_id} -> pop when src_reg is link & rd==0")
            elif src_reg:
                print(f"    Return pattern {i}: {return_spec.enable_node_id} -> pop when src_reg is link")
            else:
                print(f"    Return pattern {i}: {return_spec.enable_node_id} -> always pop (unconditional return)")

        if not call_nodes and not return_nodes:
            print("  ERROR: No valid call or return patterns found")
            return None

        # Validate required infrastructure nodes (structural - no searching)
        print("  Validating required infrastructure nodes...")

        predicted_pc = None
        if self.spec.predicted_pc_node_id:
            predicted_pc = self.graph.nodes.get(self.spec.predicted_pc_node_id)
            if predicted_pc:
                print(f"    Found predicted_pc: {self.spec.predicted_pc_node_id}")
            else:
                print(f"    ERROR: predicted_pc node '{self.spec.predicted_pc_node_id}' not found")
                return None
        else:
            print("    ERROR: predicted_pc_node_id not specified in RASSpec")
            return None

        default_prediction = None
        if self.spec.default_prediction_node_id:
            default_prediction = self.graph.nodes.get(self.spec.default_prediction_node_id)
            if default_prediction:
                print(f"    Found default_prediction: {self.spec.default_prediction_node_id}")
            else:
                print(f"    ERROR: default_prediction node '{self.spec.default_prediction_node_id}' not found")
                return None
        else:
            print("    ERROR: default_prediction_node_id not specified in RASSpec")
            return None

        control_hazard_flush = None
        if self.spec.control_hazard_flush_node_id:
            control_hazard_flush = self.graph.nodes.get(self.spec.control_hazard_flush_node_id)
            if control_hazard_flush:
                print(f"    Found control_hazard_flush: {self.spec.control_hazard_flush_node_id}")
            else:
                print(f"    ERROR: control_hazard_flush node '{self.spec.control_hazard_flush_node_id}' not found")
                return None
        else:
            print("    ERROR: control_hazard_flush_node_id not specified in RASSpec")
            return None

        jalr_target = None
        if self.spec.jalr_target_node_id:
            jalr_target = self.graph.nodes.get(self.spec.jalr_target_node_id)
            if jalr_target:
                print(f"    Found jalr_target: {self.spec.jalr_target_node_id}")
            else:
                print(f"    ERROR: jalr_target node '{self.spec.jalr_target_node_id}' not found")
                return None
        else:
            print("    ERROR: jalr_target_node_id not specified in RASSpec")
            return None

        # Optional: Execute-stage JALR enable for proper misprediction timing
        jalr_execute_enable = None
        if self.spec.jalr_execute_enable_node_id:
            jalr_execute_enable = self.graph.nodes.get(self.spec.jalr_execute_enable_node_id)
            if jalr_execute_enable:
                print(f"    Found jalr_execute_enable: {self.spec.jalr_execute_enable_node_id}")
            else:
                print(f"    Warning: jalr_execute_enable node '{self.spec.jalr_execute_enable_node_id}' not found")
                print(f"    Will create a pipelined version of ras_pop for misprediction detection")

        # Optional: Return branch taken signal for conditional returns (e.g., OpenPOWER bclr)
        return_branch_taken = None
        if self.spec.return_branch_taken_node_id:
            return_branch_taken = self.graph.nodes.get(self.spec.return_branch_taken_node_id)
            if return_branch_taken:
                print(f"    Found return_branch_taken: {self.spec.return_branch_taken_node_id}")
            else:
                print(f"    Warning: return_branch_taken node '{self.spec.return_branch_taken_node_id}' not found")
                print(f"    Will assume unconditional returns for misprediction detection")

        # Determine decode stage from enable signal timing
        decode_stage = 0
        if call_nodes:
            enable = call_nodes[0]['enable']
            if enable.uarch_time is not None:
                decode_stage = enable.uarch_time
        print(f"  Decode stage: {decode_stage}")

        return RASAnalysis(
            call_nodes=call_nodes,
            return_nodes=return_nodes,
            predicted_pc=predicted_pc,
            default_prediction=default_prediction,
            control_hazard_flush=control_hazard_flush,
            jalr_target=jalr_target,
            jalr_execute_enable=jalr_execute_enable,
            return_branch_taken=return_branch_taken,
            decode_stage=decode_stage
        )

    # =========================================================================
    # Phase 2: PLANNING
    # =========================================================================

    def _plan(self) -> Dict:
        """Create specifications for RAS hardware components."""

        ptr_width = max(1, int(math.ceil(math.log2(self.spec.ras_depth))))

        plan = {
            'ras_depth': self.spec.ras_depth,
            'ras_width': self.spec.ras_width,
            'ptr_width': ptr_width,
            'link_registers': self.spec.link_registers,
            'num_call_patterns': len(self.analysis.call_nodes),
            'num_return_patterns': len(self.analysis.return_nodes),
        }

        print(f"  RAS depth: {plan['ras_depth']} entries")
        print(f"  RAS width: {plan['ras_width']} bits")
        print(f"  Pointer width: {plan['ptr_width']} bits")
        print(f"  Link registers: {plan['link_registers']}")
        print(f"  Call patterns: {plan['num_call_patterns']}")
        print(f"  Return patterns: {plan['num_return_patterns']}")

        return plan

    # =========================================================================
    # Phase 3: STRUCTURE
    # =========================================================================

    def _create_structure(self):
        """Create skeleton nodes for RAS components."""

        ptr_width = max(1, int(math.ceil(math.log2(self.spec.ras_depth))))

        # RAS stack array (microarchitectural state)
        ras_stack = Node('ras_stack', data={
            'type': 'ras_stack',
            'name': 'ras_stack',
            'display_name': 'Return Address Stack',
            'depth': self.spec.ras_depth,
            'bit_width': self.spec.ras_width,
            'description': f'{self.spec.ras_depth}-entry Return Address Stack'
        }, is_uarch_state=True, uarch_time=0)
        self.graph.add_node(ras_stack)
        self.ras_nodes['ras_stack'] = ras_stack
        print(f"  Created ras_stack ({self.spec.ras_depth} x {self.spec.ras_width} bits)")

        # Stack pointer
        ras_ptr = Node('ras_ptr', data={
            'type': 'ras_ptr',  # Use specific type so Verilog generator handles it as register
            'name': 'ras_ptr',
            'display_name': 'RAS Stack Pointer',
            'bit_width': ptr_width,
            'description': 'Points to next free slot in RAS',
            'ras_component': True
        }, is_uarch_state=True, uarch_time=0)
        self.graph.add_node(ras_ptr)
        self.ras_nodes['ras_ptr'] = ras_ptr
        print(f"  Created ras_ptr ({ptr_width} bits)")

        # RAS top-of-stack read (predicted return address)
        ras_top = Node('ras_top', data={
            'type': 'var',
            'name': 'ras_top',
            'display_name': 'RAS Top of Stack (Predicted Return)',
            'bit_width': self.spec.ras_width,
            'description': 'Predicted return address from RAS'
        }, is_uarch_state=False, uarch_time=0)
        self.graph.add_node(ras_top)
        self.ras_nodes['ras_top'] = ras_top
        print(f"  Created ras_top (predicted return address)")

        # RAS prediction register - captures ras_top value for misprediction comparison at Execute
        # This is needed because the RAS pointer is updated immediately on pop, but the
        # misprediction check happens one cycle later in Execute stage
        ras_prediction = Node('ras_prediction', data={
            'type': 'pipeline_register',
            'name': 'ras_prediction',
            'display_name': 'RAS Prediction (pipelined for Execute)',
            'bit_width': self.spec.ras_width,
            'description': 'Predicted return address pipelined to Execute for misprediction check',
            'ras_component': True
        }, is_uarch_state=True, uarch_time=1)  # Execute stage timing
        self.graph.add_node(ras_prediction)
        self.ras_nodes['ras_prediction'] = ras_prediction
        print(f"  Created ras_prediction (pipelined for misprediction check)")

        # Push enable signal
        ras_push = Node('ras_push', data={
            'type': 'var',
            'name': 'ras_push',
            'display_name': 'RAS Push Enable',
            'bit_width': 1,
            'description': 'Asserted when call detected - push return address'
        }, is_uarch_state=False)
        self.graph.add_node(ras_push)
        self.ras_nodes['ras_push'] = ras_push
        print(f"  Created ras_push signal")

        # Pop enable signal
        ras_pop = Node('ras_pop', data={
            'type': 'var',
            'name': 'ras_pop',
            'display_name': 'RAS Pop Enable',
            'bit_width': 1,
            'description': 'Asserted when return detected - pop and predict'
        }, is_uarch_state=False)
        self.graph.add_node(ras_pop)
        self.ras_nodes['ras_pop'] = ras_pop
        print(f"  Created ras_pop signal")

        # RAS misprediction signal
        ras_mispredict = Node('ras_mispredict', data={
            'type': 'var',
            'name': 'ras_mispredict',
            'display_name': 'RAS Misprediction',
            'bit_width': 1,
            'description': 'Asserted when RAS prediction does not match actual target'
        }, is_uarch_state=False)
        self.graph.add_node(ras_mispredict)
        self.ras_nodes['ras_mispredict'] = ras_mispredict
        print(f"  Created ras_mispredict signal")

        # Flush-gated push/pop signals for stack updates
        # These prevent corrupting the RAS when instructions are flushed
        ras_push_valid = Node('ras_push_valid', data={
            'type': 'var',
            'name': 'ras_push_valid',
            'display_name': 'RAS Push Enable (flush-gated)',
            'bit_width': 1,
            'description': 'Push enable gated by !control_hazard_flush',
            'ras_component': True
        }, is_uarch_state=False)
        self.graph.add_node(ras_push_valid)
        self.ras_nodes['ras_push_valid'] = ras_push_valid
        print(f"  Created ras_push_valid signal (flush-gated)")

        ras_pop_valid = Node('ras_pop_valid', data={
            'type': 'var',
            'name': 'ras_pop_valid',
            'display_name': 'RAS Pop Enable (flush-gated)',
            'bit_width': 1,
            'description': 'Pop enable gated by !control_hazard_flush',
            'ras_component': True
        }, is_uarch_state=False)
        self.graph.add_node(ras_pop_valid)
        self.ras_nodes['ras_pop_valid'] = ras_pop_valid
        print(f"  Created ras_pop_valid signal (flush-gated)")

    # =========================================================================
    # Phase 4: HARDWARE
    # =========================================================================

    def _generate_hardware(self):
        """Generate hardware logic for RAS."""

        # Create literal nodes for link register values
        print("  Creating link register literals...")
        link_reg_literals = []
        for link_reg in self.spec.link_registers:
            literal = self.hw_factory.literals.create_or_get_literal(link_reg)
            link_reg_literals.append(literal)
            print(f"    Created literal for link register x{link_reg}")

        # Create literal for zero (for rd == 0 check in returns)
        zero_literal = self.hw_factory.literals.create_or_get_literal(0)

        # =====================================================================
        # Call Detection: push when enable && (dest_reg is link register)
        # If dest_reg is None, it's an unconditional call (always push)
        # =====================================================================
        print("  Creating call detection logic...")
        call_push_signals = []

        for i, call_info in enumerate(self.analysis.call_nodes):
            enable_node = call_info['enable']
            dest_reg_node = call_info['dest_reg']  # Can be None for unconditional calls
            prefix = f"ras_call_{i}"

            if dest_reg_node is None:
                # Unconditional call - just use the enable signal directly
                # This is for instructions like MIPS JAL that always write to the link register
                print(f"    Call pattern {i}: unconditional (always push when enabled)")
                call_push_signals.append(enable_node)
                continue

            # Create comparators for dest_reg against each link register
            link_checks = []
            for j, (link_reg, literal) in enumerate(zip(self.spec.link_registers, link_reg_literals)):
                comp = self.hw_factory.comparators.create_index_comparator(
                    comp_id=f"{prefix}_rd_eq_{link_reg}",
                    left_node=dest_reg_node,
                    right_node=literal,
                    operator='==',
                    display_name=f"rd == {link_reg}",
                    metadata={'ras_component': True, 'check_type': 'link_register'}
                )
                link_checks.append(comp)
                print(f"    Created {comp.id}")

            # OR the link register checks together
            if len(link_checks) == 1:
                rd_is_link = link_checks[0]
            else:
                rd_is_link = Node(f"{prefix}_rd_is_link", data={
                    'type': 'operation',
                    'operator': '||',
                    'name': f"{prefix}_rd_is_link",
                    'display_name': f"rd is link register",
                    'bit_width': 1,
                    'ras_component': True
                })
                self.graph.add_node(rd_is_link)
                # Connect inputs to OR gate
                for check in link_checks:
                    edge = Edge(check, rd_is_link, data={'type': 'operand'})
                    self.graph.add_edge(edge)
                print(f"    Created {rd_is_link.id} (OR of link checks)")

            # AND with instruction enable
            is_call = Node(f"{prefix}_is_call", data={
                'type': 'operation',
                'operator': '&&',
                'name': f"{prefix}_is_call",
                'display_name': f"Call detected ({call_info['spec'].enable_node_id})",
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(is_call)

            # Connect enable and rd_is_link to AND gate
            edge1 = Edge(enable_node, is_call, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(rd_is_link, is_call, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)

            call_push_signals.append(is_call)
            print(f"    Created {is_call.id}")

        # =====================================================================
        # Return Detection: pop when enable && (src_reg is link) && (dest_reg == 0)
        # If src_reg is None, it's an unconditional return from link register
        # If dest_reg is None, skip the rd==0 check (return instruction that never links)
        # =====================================================================
        print("  Creating return detection logic...")
        return_pop_signals = []

        for i, return_info in enumerate(self.analysis.return_nodes):
            enable_node = return_info['enable']
            src_reg_node = return_info['src_reg']    # Can be None for unconditional returns from LR
            dest_reg_node = return_info['dest_reg']  # Can be None for returns that never link
            prefix = f"ras_return_{i}"

            # If both src_reg and dest_reg are None, it's an unconditional return
            if src_reg_node is None and dest_reg_node is None:
                # Unconditional return - just use the enable signal directly
                # This is for instructions like OpenPOWER bclr that always read from LR
                print(f"    Return pattern {i}: unconditional (always pop when enabled)")
                return_pop_signals.append(enable_node)
                continue

            # Build up the return pattern conditions
            conditions = []

            # Check src_reg against link registers (if src_reg is specified)
            if src_reg_node is not None:
                link_checks = []
                for j, (link_reg, literal) in enumerate(zip(self.spec.link_registers, link_reg_literals)):
                    comp = self.hw_factory.comparators.create_index_comparator(
                        comp_id=f"{prefix}_rs1_eq_{link_reg}",
                        left_node=src_reg_node,
                        right_node=literal,
                        operator='==',
                        display_name=f"rs1 == {link_reg}",
                        metadata={'ras_component': True, 'check_type': 'link_register'}
                    )
                    link_checks.append(comp)
                    print(f"    Created {comp.id}")

                # OR the link register checks together
                if len(link_checks) == 1:
                    rs1_is_link = link_checks[0]
                else:
                    rs1_is_link = Node(f"{prefix}_rs1_is_link", data={
                        'type': 'operation',
                        'operator': '||',
                        'name': f"{prefix}_rs1_is_link",
                        'display_name': f"rs1 is link register",
                        'bit_width': 1,
                        'ras_component': True
                    })
                    self.graph.add_node(rs1_is_link)
                    for check in link_checks:
                        edge = Edge(check, rs1_is_link, data={'type': 'operand'})
                        self.graph.add_edge(edge)
                    print(f"    Created {rs1_is_link.id}")

                conditions.append(rs1_is_link)

            # Check dest_reg == 0 (if dest_reg is specified)
            if dest_reg_node is not None:
                rd_is_zero = self.hw_factory.comparators.create_index_comparator(
                    comp_id=f"{prefix}_rd_eq_0",
                    left_node=dest_reg_node,
                    right_node=zero_literal,
                    operator='==',
                    display_name=f"rd == 0",
                    metadata={'ras_component': True, 'check_type': 'return_pattern'}
                )
                print(f"    Created {rd_is_zero.id}")
                conditions.append(rd_is_zero)

            # Build the return pattern from conditions
            if len(conditions) == 0:
                # Should not happen (both None was handled above)
                print(f"    Return pattern {i}: unconditional (always pop when enabled)")
                return_pop_signals.append(enable_node)
                continue
            elif len(conditions) == 1:
                is_return_pattern = conditions[0]
            else:
                # AND: rs1_is_link && rd_is_zero
                is_return_pattern = Node(f"{prefix}_pattern", data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': f"{prefix}_pattern",
                    'display_name': f"Return pattern (rs1=link, rd=0)",
                    'bit_width': 1,
                    'ras_component': True
                })
                self.graph.add_node(is_return_pattern)
                edge1 = Edge(conditions[0], is_return_pattern, data={'type': 'operand', 'position': 'left'})
                edge2 = Edge(conditions[1], is_return_pattern, data={'type': 'operand', 'position': 'right'})
                self.graph.add_edge(edge1)
                self.graph.add_edge(edge2)
                print(f"    Created {is_return_pattern.id}")

            # AND with instruction enable
            is_return = Node(f"{prefix}_is_return", data={
                'type': 'operation',
                'operator': '&&',
                'name': f"{prefix}_is_return",
                'display_name': f"Return detected ({return_info['spec'].enable_node_id})",
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(is_return)
            edge1 = Edge(enable_node, is_return, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(is_return_pattern, is_return, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)

            return_pop_signals.append(is_return)
            print(f"    Created {is_return.id}")

        # =====================================================================
        # Combine call signals into ras_push
        # =====================================================================
        print("  Combining call signals into ras_push...")
        ras_push = self.ras_nodes['ras_push']

        if len(call_push_signals) == 0:
            # No calls - push is always 0
            zero_node = self.hw_factory.literals.create_or_get_literal(0)
            edge = Edge(zero_node, ras_push, data={'type': 'assignment'})
            self.graph.add_edge(edge)
        elif len(call_push_signals) == 1:
            # Single call pattern
            edge = Edge(call_push_signals[0], ras_push, data={'type': 'assignment'})
            self.graph.add_edge(edge)
        else:
            # Multiple call patterns - OR them together
            or_result = call_push_signals[0]
            for j, signal in enumerate(call_push_signals[1:], 1):
                new_or = Node(f"ras_push_or_{j}", data={
                    'type': 'operation',
                    'operator': '||',
                    'name': f"ras_push_or_{j}",
                    'display_name': 'RAS push (any call)',
                    'bit_width': 1,
                    'ras_component': True
                })
                self.graph.add_node(new_or)
                edge1 = Edge(or_result, new_or, data={'type': 'operand', 'position': 'left'})
                edge2 = Edge(signal, new_or, data={'type': 'operand', 'position': 'right'})
                self.graph.add_edge(edge1)
                self.graph.add_edge(edge2)
                or_result = new_or

            edge = Edge(or_result, ras_push, data={'type': 'assignment'})
            self.graph.add_edge(edge)
        print(f"    Connected {len(call_push_signals)} call patterns to ras_push")

        # =====================================================================
        # Combine return signals into ras_pop
        # =====================================================================
        print("  Combining return signals into ras_pop...")
        ras_pop = self.ras_nodes['ras_pop']

        if len(return_pop_signals) == 0:
            # No returns - pop is always 0
            zero_node = self.hw_factory.literals.create_or_get_literal(0)
            edge = Edge(zero_node, ras_pop, data={'type': 'assignment'})
            self.graph.add_edge(edge)
        elif len(return_pop_signals) == 1:
            # Single return pattern
            edge = Edge(return_pop_signals[0], ras_pop, data={'type': 'assignment'})
            self.graph.add_edge(edge)
        else:
            # Multiple return patterns - OR them together
            or_result = return_pop_signals[0]
            for j, signal in enumerate(return_pop_signals[1:], 1):
                new_or = Node(f"ras_pop_or_{j}", data={
                    'type': 'operation',
                    'operator': '||',
                    'name': f"ras_pop_or_{j}",
                    'display_name': 'RAS pop (any return)',
                    'bit_width': 1,
                    'ras_component': True
                })
                self.graph.add_node(new_or)
                edge1 = Edge(or_result, new_or, data={'type': 'operand', 'position': 'left'})
                edge2 = Edge(signal, new_or, data={'type': 'operand', 'position': 'right'})
                self.graph.add_edge(edge1)
                self.graph.add_edge(edge2)
                or_result = new_or

            edge = Edge(or_result, ras_pop, data={'type': 'assignment'})
            self.graph.add_edge(edge)
        print(f"    Connected {len(return_pop_signals)} return patterns to ras_pop")

        # =====================================================================
        # Create RAS stack pointer update logic
        # =====================================================================
        print("  Creating stack pointer update logic...")
        ptr_width = max(1, int(math.ceil(math.log2(self.spec.ras_depth))))
        ras_ptr = self.ras_nodes['ras_ptr']
        ras_push = self.ras_nodes['ras_push']
        ras_pop = self.ras_nodes['ras_pop']

        # ras_ptr + 1 (for push)
        one_literal = self.hw_factory.literals.create_or_get_literal(1)
        ras_ptr_inc = Node('ras_ptr_inc', data={
            'type': 'operation',
            'operator': '+',
            'name': 'ras_ptr_inc',
            'display_name': 'ras_ptr + 1',
            'bit_width': ptr_width,
            'ras_component': True
        })
        self.graph.add_node(ras_ptr_inc)
        edge1 = Edge(ras_ptr, ras_ptr_inc, data={'type': 'operand', 'position': 'left'})
        edge2 = Edge(one_literal, ras_ptr_inc, data={'type': 'operand', 'position': 'right'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)
        print(f"    Created ras_ptr_inc")

        # ras_ptr - 1 (for pop)
        ras_ptr_dec = Node('ras_ptr_dec', data={
            'type': 'operation',
            'operator': '-',
            'name': 'ras_ptr_dec',
            'display_name': 'ras_ptr - 1',
            'bit_width': ptr_width,
            'ras_component': True
        })
        self.graph.add_node(ras_ptr_dec)
        edge1 = Edge(ras_ptr, ras_ptr_dec, data={'type': 'operand', 'position': 'left'})
        edge2 = Edge(one_literal, ras_ptr_dec, data={'type': 'operand', 'position': 'right'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)
        print(f"    Created ras_ptr_dec")

        # Mux for pointer update: push -> inc, pop -> dec, else unchanged
        ras_ptr_next = Node('ras_ptr_next', data={
            'type': 'ras_ptr_update',
            'name': 'ras_ptr_next',
            'display_name': 'RAS pointer next value',
            'bit_width': ptr_width,
            'ras_component': True,
            'push_signal': 'ras_push',
            'pop_signal': 'ras_pop',
            'ptr_inc': 'ras_ptr_inc',
            'ptr_dec': 'ras_ptr_dec',
            'ptr_current': 'ras_ptr'
        })
        self.graph.add_node(ras_ptr_next)
        self.ras_nodes['ras_ptr_next'] = ras_ptr_next

        # Connect inputs to ptr_next mux
        edge1 = Edge(ras_push, ras_ptr_next, data={'type': 'control', 'signal': 'push'})
        edge2 = Edge(ras_pop, ras_ptr_next, data={'type': 'control', 'signal': 'pop'})
        edge3 = Edge(ras_ptr_inc, ras_ptr_next, data={'type': 'mux_input', 'input_index': 0, 'condition': 'push'})
        edge4 = Edge(ras_ptr_dec, ras_ptr_next, data={'type': 'mux_input', 'input_index': 1, 'condition': 'pop'})
        edge5 = Edge(ras_ptr, ras_ptr_next, data={'type': 'mux_default_input'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)
        self.graph.add_edge(edge3)
        self.graph.add_edge(edge4)
        self.graph.add_edge(edge5)
        print(f"    Created ras_ptr_next mux")

        # Connect ras_ptr_next back to ras_ptr (register update)
        edge = Edge(ras_ptr_next, ras_ptr, data={'type': 'assignment', 'register_update': True})
        self.graph.add_edge(edge)

        # =====================================================================
        # Create RAS read logic (top of stack for prediction)
        # =====================================================================
        print("  Creating RAS read logic...")
        ras_top = self.ras_nodes['ras_top']
        ras_stack = self.ras_nodes['ras_stack']

        # ras_top = ras_stack[ras_ptr - 1]
        # The read index is ptr - 1 (since ptr points to next free slot)
        ras_read_idx = Node('ras_read_idx', data={
            'type': 'operation',
            'operator': '-',
            'name': 'ras_read_idx',
            'display_name': 'ras_ptr - 1 (TOS index)',
            'bit_width': ptr_width,
            'ras_component': True
        })
        self.graph.add_node(ras_read_idx)
        edge1 = Edge(ras_ptr, ras_read_idx, data={'type': 'operand', 'position': 'left'})
        edge2 = Edge(one_literal, ras_read_idx, data={'type': 'operand', 'position': 'right'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)
        print(f"    Created ras_read_idx")

        # Connect stack read
        ras_stack_read = Node('ras_stack_read', data={
            'type': 'array_read',
            'name': 'ras_stack_read',
            'display_name': 'ras_stack[ras_ptr-1]',
            'bit_width': self.spec.ras_width,
            'array': 'ras_stack',
            'ras_component': True
        })
        self.graph.add_node(ras_stack_read)
        edge1 = Edge(ras_stack, ras_stack_read, data={'type': 'array_base'})
        edge2 = Edge(ras_read_idx, ras_stack_read, data={'type': 'array_index'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)

        # Connect to ras_top
        edge = Edge(ras_stack_read, ras_top, data={'type': 'assignment'})
        self.graph.add_edge(edge)
        print(f"    Created ras_stack_read -> ras_top")

        # =====================================================================
        # Create RAS write logic (push return address)
        # =====================================================================
        print("  Creating RAS write logic...")

        # Get return address from first call pattern (they should all use the same)
        if self.analysis.call_nodes:
            return_addr_node = self.analysis.call_nodes[0]['return_addr']

            # IMPORTANT: The return address node from the spec might get pipelined
            # to a later stage (e.g., Execute) by the pipeline insertion pass because
            # it's also used by the RF write. But the RAS stack write happens at
            # Decode stage, so we need a Decode-stage copy of the return address.
            #
            # We need to use the DECODE-stage PC (PIPE_Decode_pc_rd_PIPE), not the
            # FETCH-stage PC (pc_rd). When JAL is in Decode:
            #   - pc_rd = next instruction address (Fetch stage)
            #   - PIPE_Decode_pc_rd_PIPE = JAL's address (Decode stage)
            #
            # For MIPS, return_addr is JAL_addr + 8 = PIPE_Decode_pc_rd_PIPE + 8
            # For RISC-V, return_addr is JAL_addr + 4 = PIPE_Decode_pc_rd_PIPE + 4
            #
            # Find the Decode-stage pipelined PC
            decode_pc_node = self.graph.nodes.get('PIPE_Decode_pc_rd_PIPE')
            if decode_pc_node:
                # Determine the offset from the original return address node
                # If return_addr is (pc + 8), offset is 8; if (pc + 4), offset is 4
                offset = 4  # Default for RISC-V
                ret_addr_name = return_addr_node.id.lower()
                if '+ 8' in ret_addr_name or 'plus_8' in ret_addr_name or 'pc_plus_8' in ret_addr_name:
                    offset = 8
                elif '+ 4' in ret_addr_name or 'plus_4' in ret_addr_name or 'pc_plus_4' in ret_addr_name:
                    offset = 4

                # Create the offset literal
                offset_literal = self.hw_factory.literals.create_or_get_literal(offset)

                # Create ras_return_addr = PIPE_Decode_pc_rd_PIPE + offset at Decode stage
                ras_return_addr = Node('ras_return_addr', data={
                    'type': 'operation',
                    'operator': '+',
                    'name': 'ras_return_addr',
                    'display_name': f'RAS return address (PIPE_Decode_pc_rd_PIPE + {offset})',
                    'bit_width': self.spec.ras_width,
                    'ras_component': True,
                    'description': 'Decode-stage return address for RAS push'
                }, uarch_time=self.analysis.decode_stage)
                self.graph.add_node(ras_return_addr)

                edge1 = Edge(decode_pc_node, ras_return_addr, data={'type': 'operand', 'position': 'left'})
                edge2 = Edge(offset_literal, ras_return_addr, data={'type': 'operand', 'position': 'right'})
                self.graph.add_edge(edge1)
                self.graph.add_edge(edge2)

                self.ras_nodes['ras_return_addr'] = ras_return_addr
                print(f"    Created ras_return_addr = PIPE_Decode_pc_rd_PIPE + {offset} (Decode stage)")

                # Use our Decode-stage return address for the RAS write
                ras_write_data = ras_return_addr
            else:
                # Fallback: use the original return address node (may have timing issues)
                print(f"    WARNING: PIPE_Decode_pc_rd_PIPE not found, using original return_addr node (may have timing issues)")
                ras_write_data = return_addr_node

            ras_stack_write = Node('ras_stack_write', data={
                'type': 'array_write',
                'name': 'ras_stack_write',
                'display_name': 'ras_stack[ras_ptr] = ret_addr',
                'bit_width': self.spec.ras_width,
                'array': 'ras_stack',
                'ras_component': True
            })
            self.graph.add_node(ras_stack_write)

            # Connect write components
            edge1 = Edge(ras_stack, ras_stack_write, data={'type': 'array_base'})
            edge2 = Edge(ras_ptr, ras_stack_write, data={'type': 'write_address'})
            edge3 = Edge(ras_write_data, ras_stack_write, data={'type': 'write_data'})
            edge4 = Edge(ras_push, ras_stack_write, data={'type': 'write_enable'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)
            self.graph.add_edge(edge3)
            self.graph.add_edge(edge4)
            print(f"    Created ras_stack_write (push from {ras_write_data.id})")

    # =========================================================================
    # Phase 5: CONNECTION
    # =========================================================================

    def _wire_components(self):
        """Wire RAS components to existing prediction infrastructure."""

        ras_top = self.ras_nodes['ras_top']
        ras_pop = self.ras_nodes['ras_pop']
        ras_push = self.ras_nodes['ras_push']
        ras_mispredict = self.ras_nodes['ras_mispredict']
        ras_push_valid = self.ras_nodes['ras_push_valid']
        ras_pop_valid = self.ras_nodes['ras_pop_valid']

        # Use structural nodes from analysis (no searching!)
        predicted_pc = self.analysis.predicted_pc
        default_prediction = self.analysis.default_prediction
        control_hazard_flush = self.analysis.control_hazard_flush
        jalr_target = self.analysis.jalr_target
        jalr_execute_enable = self.analysis.jalr_execute_enable

        # =====================================================================
        # Gate ras_pop by Decode stage validity (for architectures that need it)
        #
        # For architectures WITHOUT validity-gated enables (like MIPS), the return
        # instruction can be stale after a flush (decoded from stale bits). We need
        # to gate ras_pop by PIPE_Decode_valid_PIPE to prevent spurious pops.
        #
        # For architectures WITH validity-gated enables (like OpenPOWER), the return
        # enable (e.g., bclr_enable_valid) already includes PIPE_Decode_valid_PIPE.
        # Adding extra gating would cause timing issues due to the one-cycle delay
        # in the validity register, blocking valid returns after a flush.
        #
        # For architectures without delay slots (skip_validity_gating=True), we also
        # skip the extra gating because flush gating is sufficient.
        # =====================================================================
        # Check if the return enable is already validity-gated
        return_enable_is_validity_gated = False
        if self.analysis.return_nodes:
            first_return_enable = self.analysis.return_nodes[0]['enable']
            if first_return_enable.id.endswith('_valid'):
                return_enable_is_validity_gated = True
                print(f"  Return enable '{first_return_enable.id}' is already validity-gated - skipping additional gating")

        # Check if spec explicitly requests combinational validity gating
        use_combinational_validity = self.spec.use_combinational_validity

        # For architectures without validity-gated enables, create ras_pop_decode_gated
        # to properly gate RAS operations with Decode stage validity
        if not return_enable_is_validity_gated:
            # Choose validity signal based on architecture characteristics:
            # - Architectures with delay slots (MIPS32): use REGISTERED signal
            #   (PIPE_Decode_valid_PIPE) to block stale instructions from before flush
            # - Architectures without delay slots (OpenPOWER): use COMBINATIONAL signal
            #   (PIPE_Decode_valid_not_flush) to avoid timing delay after branches
            if use_combinational_validity:
                decode_valid = self.graph.nodes.get('PIPE_Decode_valid_not_flush')
                if decode_valid:
                    print(f"  use_combinational_validity=True - using {decode_valid.id} (no delay slots)")
                else:
                    # Fallback to registered if combinational not found
                    decode_valid = self.graph.nodes.get('PIPE_Decode_valid_PIPE')
                    if decode_valid:
                        print(f"  WARNING: PIPE_Decode_valid_not_flush not found, falling back to {decode_valid.id}")
            else:
                decode_valid = self.graph.nodes.get('PIPE_Decode_valid_PIPE')
                if decode_valid:
                    print(f"  Using registered validity signal {decode_valid.id} (for delay slot architectures)")
                else:
                    # Fallback to combinational if registered not found
                    decode_valid = self.graph.nodes.get('PIPE_Decode_valid_not_flush')
                    if decode_valid:
                        print(f"  WARNING: PIPE_Decode_valid_PIPE not found, falling back to {decode_valid.id}")
            if decode_valid:
                print(f"  Found Decode validity signal: {decode_valid.id}")

                # Create ras_pop_decode_gated = ras_pop && decode_valid
                # This gates stack operations with Decode validity
                ras_pop_gated = Node('ras_pop_decode_gated', data={
                    'type': 'operation',
                    'operator': '&&',
                    'name': 'ras_pop_decode_gated',
                    'display_name': 'ras_pop && decode_valid',
                    'bit_width': 1,
                    'ras_component': True
                })
                self.graph.add_node(ras_pop_gated)
                edge1 = Edge(ras_pop, ras_pop_gated, data={'type': 'operand', 'position': 'left'})
                edge2 = Edge(decode_valid, ras_pop_gated, data={'type': 'operand', 'position': 'right'})
                self.graph.add_edge(edge1)
                self.graph.add_edge(edge2)
                print(f"    Created ras_pop_decode_gated = ras_pop && {decode_valid.id}")

                # Store for later use (ras_prediction write enable)
                self.ras_nodes['ras_pop_decode_gated'] = ras_pop_gated

                # Use the gated version for stack operations
                ras_pop = ras_pop_gated
            else:
                print("  WARNING: PIPE_Decode_valid_not_flush not found - ras_pop may have spurious triggers after flush")

        # =====================================================================
        # Create flush-gated and stall-gated push/pop signals
        # These prevent corrupting the RAS when instructions are flushed or stalled
        # =====================================================================
        print("  Creating flush/stall-gated push/pop signals...")

        # Create !control_hazard_flush node
        flush_not = Node('control_hazard_flush_not_ras', data={
            'type': 'operation',
            'operator': '!',
            'name': 'control_hazard_flush_not_ras',
            'display_name': '!control_hazard_flush (for RAS)',
            'bit_width': 1,
            'ras_component': True
        })
        self.graph.add_node(flush_not)
        edge = Edge(control_hazard_flush, flush_not, data={'type': 'operand'})
        self.graph.add_edge(edge)

        # Find the Decode stall controller structurally
        # The RAS operates at Decode stage, so we need to gate with the Decode stall
        source_node_id = self.analysis.call_nodes[0]['enable'].id if self.analysis.call_nodes else None
        decode_stall_ctrl = self._find_stall_controller_for_stage(source_node_id) if source_node_id else None

        # Create !stall node if stall controller found
        stall_not = None
        if decode_stall_ctrl:
            stall_not = Node('ras_stall_not', data={
                'type': 'operation',
                'operator': '!',
                'name': 'ras_stall_not',
                'display_name': '!stall (for RAS)',
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(stall_not)
            edge = Edge(decode_stall_ctrl, stall_not, data={'type': 'operand'})
            self.graph.add_edge(edge)
            print(f"    Found Decode stall controller: {decode_stall_ctrl.id}")

        # ras_push_valid = ras_push && !control_hazard_flush && !stall
        # First: ras_push && !flush
        push_and_not_flush = Node('ras_push_and_not_flush', data={
            'type': 'operation',
            'operator': '&&',
            'name': 'ras_push_and_not_flush',
            'display_name': 'ras_push && !flush',
            'bit_width': 1,
            'ras_component': True
        })
        self.graph.add_node(push_and_not_flush)
        edge1 = Edge(ras_push, push_and_not_flush, data={'type': 'operand', 'position': 'left'})
        edge2 = Edge(flush_not, push_and_not_flush, data={'type': 'operand', 'position': 'right'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)

        if stall_not:
            # Then: (ras_push && !flush) && !stall
            push_valid_and = Node('ras_push_valid_and', data={
                'type': 'operation',
                'operator': '&&',
                'name': 'ras_push_valid_and',
                'display_name': 'ras_push && !flush && !stall',
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(push_valid_and)
            edge1 = Edge(push_and_not_flush, push_valid_and, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(stall_not, push_valid_and, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)
            edge3 = Edge(push_valid_and, ras_push_valid, data={'type': 'assignment'})
            self.graph.add_edge(edge3)
            print(f"    Created ras_push_valid = ras_push && !flush && !stall")
        else:
            # No stall controller found - just use flush gating
            edge3 = Edge(push_and_not_flush, ras_push_valid, data={'type': 'assignment'})
            self.graph.add_edge(edge3)
            print(f"    Created ras_push_valid = ras_push && !flush (no stall controller found)")

        # ras_pop_valid = ras_pop && !control_hazard_flush && !stall
        # First: ras_pop && !flush
        pop_and_not_flush = Node('ras_pop_and_not_flush', data={
            'type': 'operation',
            'operator': '&&',
            'name': 'ras_pop_and_not_flush',
            'display_name': 'ras_pop && !flush',
            'bit_width': 1,
            'ras_component': True
        })
        self.graph.add_node(pop_and_not_flush)
        edge1 = Edge(ras_pop, pop_and_not_flush, data={'type': 'operand', 'position': 'left'})
        edge2 = Edge(flush_not, pop_and_not_flush, data={'type': 'operand', 'position': 'right'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)

        if stall_not:
            # Then: (ras_pop && !flush) && !stall
            pop_valid_and = Node('ras_pop_valid_and', data={
                'type': 'operation',
                'operator': '&&',
                'name': 'ras_pop_valid_and',
                'display_name': 'ras_pop && !flush && !stall',
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(pop_valid_and)
            edge1 = Edge(pop_and_not_flush, pop_valid_and, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(stall_not, pop_valid_and, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)
            edge3 = Edge(pop_valid_and, ras_pop_valid, data={'type': 'assignment'})
            self.graph.add_edge(edge3)
            print(f"    Created ras_pop_valid = ras_pop && !flush && !stall")
        else:
            # No stall controller found - just use flush gating
            edge3 = Edge(pop_and_not_flush, ras_pop_valid, data={'type': 'assignment'})
            self.graph.add_edge(edge3)
            print(f"    Created ras_pop_valid = ras_pop && !flush (no stall controller found)")

        # =====================================================================
        # Create misprediction detection using structural jalr_target
        # IMPORTANT: jalr_target is computed from Execute stage values (rs1, imm),
        # so we must use Execute-stage return detection for proper timing.
        # We also need to use a pipelined version of ras_top (ras_prediction)
        # because the RAS pointer is updated immediately on pop (Decode),
        # but the comparison happens one cycle later (Execute).
        # =====================================================================
        print("  Creating misprediction detection...")
        print(f"    Using jalr_target: {jalr_target.id}")

        # Get the ras_prediction register (captures ras_top for comparison at Execute)
        ras_prediction = self.ras_nodes['ras_prediction']

        # Connect ras_top -> ras_prediction (pipeline the prediction value)
        edge = Edge(ras_top, ras_prediction, data={'type': 'pipeline_input', 'stages': 1})
        self.graph.add_edge(edge)
        print(f"    Connected ras_top -> ras_prediction (pipelining prediction value)")

        # IMPORTANT: Add valid_gate so ras_prediction only captures when a return is decoded
        # Without this, ras_prediction would update every cycle, overwriting the correct
        # prediction value with whatever ras_top is after the stack pointer changed.
        # Using 'valid_gate' edge type because that's what the Verilog generator supports
        # for conditional pipeline register updates.
        ras_pop_decode_gated = self.ras_nodes.get('ras_pop_decode_gated', ras_pop)
        valid_gate_edge = Edge(ras_pop_decode_gated, ras_prediction, data={'type': 'valid_gate'})
        self.graph.add_edge(valid_gate_edge)
        print(f"    Added valid_gate from {ras_pop_decode_gated.id} to ras_prediction")

        # Add stall edge to properly gate ras_prediction with the stall controller
        # that gates the transition from the RAS source stage to the next stage.
        # Find the controller structurally by looking at a known node at the RAS stage.
        source_node_id = self.analysis.call_nodes[0]['enable'].id if self.analysis.call_nodes else None
        decode_stall_ctrl = self._find_stall_controller_for_stage(source_node_id) if source_node_id else None
        if decode_stall_ctrl:
            stall_edge = Edge(decode_stall_ctrl, ras_prediction, data={'type': 'stall'})
            self.graph.add_edge(stall_edge)
            print(f"    Added stall edge from {decode_stall_ctrl.id} to ras_prediction")
        else:
            print(f"    WARNING: Could not find decode stall controller - ras_prediction may not be properly gated")

        # Compare RAS prediction (pipelined) with actual target
        # Using ras_prediction ensures we compare the value that was valid when ras_pop fired
        mispredict_cmp = self.hw_factory.comparators.create_index_comparator(
            comp_id='ras_mispredict_cmp',
            left_node=ras_prediction,  # Use pipelined value, not ras_top
            right_node=jalr_target,
            operator='!=',
            display_name='RAS prediction != actual target',
            metadata={'ras_component': True}
        )
        print(f"    Created ras_mispredict_cmp (using pipelined ras_prediction)")

        # Determine which signal to use for Execute-stage return detection
        # We need an Execute-stage version of the return detection for proper timing
        # with jalr_target (which is also Execute stage).
        ras_return_execute = None

        if jalr_execute_enable:
            # If jalr_execute_enable is provided, we need to AND it with the
            # return pattern detection. Since the return pattern (rs1 is link, rd==0)
            # is also determined at Decode time and doesn't change as the instruction
            # moves through the pipeline, we need to pipeline the return pattern.
            #
            # For now, use jalr_execute_enable && (ras_pop delayed one cycle)
            # This works because ras_pop = jalr_enable && return_pattern,
            # and if jalr_execute_enable is high for the same instruction,
            # the return pattern is still valid.
            print(f"    Using Execute-stage JALR enable: {jalr_execute_enable.id}")

            # Create a pipelined version of the return pattern detection
            # ras_pop is (jalr_enable && return_pattern) at Decode
            # We need (jalr_execute_enable && return_pattern_pipelined) at Execute
            #
            # Since return_pattern only depends on instruction fields (rs1, rd)
            # which don't change as the instruction progresses, we can use:
            # ras_return_execute = jalr_execute_enable && return_pattern_pipelined
            #
            # The cleanest way: Create a "ras_return_pattern" node that gets
            # pipelined, then AND with jalr_execute_enable.
            #
            # For simplicity, we'll create a pipelined ras_pop register.
            ras_pop_execute = Node('ras_pop_execute', data={
                'type': 'pipeline_register',
                'name': 'ras_pop_execute',
                'display_name': 'RAS pop at Execute stage',
                'bit_width': 1,
                'ras_component': True,
                'pipeline_stage': 'Execute',
                'source_signal': 'ras_pop'
            }, is_uarch_state=True, uarch_time=self.analysis.decode_stage + 1)
            self.graph.add_node(ras_pop_execute)

            # Connect ras_pop -> ras_pop_execute (pipelining)
            edge = Edge(ras_pop, ras_pop_execute, data={'type': 'pipeline_input', 'stages': 1})
            self.graph.add_edge(edge)
            print(f"    Created ras_pop_execute (pipelined ras_pop for Execute stage)")

            # Add stall edge to properly gate the pipeline register
            # This ensures ras_pop_execute only updates when an instruction advances to the next stage
            # Find the controller structurally by looking at a known node at the RAS stage
            source_node_id = self.analysis.call_nodes[0]['enable'].id if self.analysis.call_nodes else None
            stall_ctrl = self._find_stall_controller_for_stage(source_node_id) if source_node_id else None
            if stall_ctrl:
                stall_edge = Edge(stall_ctrl, ras_pop_execute, data={'type': 'stall'})
                self.graph.add_edge(stall_edge)
                print(f"    Added stall edge from {stall_ctrl.id} to ras_pop_execute")
            else:
                print(f"    WARNING: Could not find stall controller - ras_pop_execute may not be properly gated")

            self.ras_nodes['ras_pop_execute'] = ras_pop_execute

            # Gate ras_pop_execute by Execute stage validity for architectures
            # that don't have validity-gated enables. This prevents flush signals
            # from firing for invalidated instructions.
            if not return_enable_is_validity_gated:
                execute_valid = self.graph.nodes.get('PIPE_Execute_valid_PIPE')
                if execute_valid:
                    ras_pop_execute_valid = Node('ras_pop_execute_valid', data={
                        'type': 'operation',
                        'operator': '&&',
                        'name': 'ras_pop_execute_valid',
                        'display_name': 'RAS pop at Execute (validity-gated)',
                        'bit_width': 1,
                        'ras_component': True
                    })
                    self.graph.add_node(ras_pop_execute_valid)
                    edge1 = Edge(ras_pop_execute, ras_pop_execute_valid, data={'type': 'operand', 'position': 'left'})
                    edge2 = Edge(execute_valid, ras_pop_execute_valid, data={'type': 'operand', 'position': 'right'})
                    self.graph.add_edge(edge1)
                    self.graph.add_edge(edge2)
                    ras_return_execute = ras_pop_execute_valid
                    print(f"    Created ras_pop_execute_valid (gated by PIPE_Execute_valid_PIPE)")
                else:
                    ras_return_execute = ras_pop_execute
                    print(f"    WARNING: PIPE_Execute_valid_PIPE not found, using ungated ras_pop_execute")
            else:
                ras_return_execute = ras_pop_execute
        else:
            # No Execute-stage enable provided - we'll need to create the
            # misprediction detection differently.
            #
            # IMPORTANT: This case leads to stage mismatch!
            # If jalr_execute_enable is not provided, the misprediction detection
            # will compare Decode-stage ras_pop with Execute-stage jalr_target,
            # which is incorrect.
            #
            # To fix this, we create a pipelined version of ras_pop.
            print("    WARNING: No Execute-stage JALR enable provided")
            print("    Creating pipelined ras_pop for proper misprediction timing")

            ras_pop_execute = Node('ras_pop_execute', data={
                'type': 'pipeline_register',
                'name': 'ras_pop_execute',
                'display_name': 'RAS pop at Execute stage',
                'bit_width': 1,
                'ras_component': True,
                'pipeline_stage': 'Execute'
            }, is_uarch_state=True, uarch_time=self.analysis.decode_stage + 1)
            self.graph.add_node(ras_pop_execute)

            # Connect ras_pop -> ras_pop_execute
            edge = Edge(ras_pop, ras_pop_execute, data={'type': 'pipeline_input', 'stages': 1})
            self.graph.add_edge(edge)
            print(f"    Created ras_pop_execute (pipelined ras_pop)")

            # Add stall edge to properly gate the pipeline register
            # Find the controller structurally by looking at a known node at the RAS stage
            source_node_id = self.analysis.call_nodes[0]['enable'].id if self.analysis.call_nodes else None
            stall_ctrl = self._find_stall_controller_for_stage(source_node_id) if source_node_id else None
            if stall_ctrl:
                stall_edge = Edge(stall_ctrl, ras_pop_execute, data={'type': 'stall'})
                self.graph.add_edge(stall_edge)
                print(f"    Added stall edge from {stall_ctrl.id} to ras_pop_execute")
            else:
                print(f"    WARNING: Could not find stall controller - ras_pop_execute may not be properly gated")

            self.ras_nodes['ras_pop_execute'] = ras_pop_execute

            # Gate ras_pop_execute by Execute stage validity for architectures
            # that don't have validity-gated enables.
            if not return_enable_is_validity_gated:
                execute_valid = self.graph.nodes.get('PIPE_Execute_valid_PIPE')
                if execute_valid:
                    ras_pop_execute_valid = Node('ras_pop_execute_valid', data={
                        'type': 'operation',
                        'operator': '&&',
                        'name': 'ras_pop_execute_valid',
                        'display_name': 'RAS pop at Execute (validity-gated)',
                        'bit_width': 1,
                        'ras_component': True
                    })
                    self.graph.add_node(ras_pop_execute_valid)
                    edge1 = Edge(ras_pop_execute, ras_pop_execute_valid, data={'type': 'operand', 'position': 'left'})
                    edge2 = Edge(execute_valid, ras_pop_execute_valid, data={'type': 'operand', 'position': 'right'})
                    self.graph.add_edge(edge1)
                    self.graph.add_edge(edge2)
                    ras_return_execute = ras_pop_execute_valid
                    print(f"    Created ras_pop_execute_valid (gated by PIPE_Execute_valid_PIPE)")
                else:
                    ras_return_execute = ras_pop_execute
                    print(f"    WARNING: PIPE_Execute_valid_PIPE not found, using ungated ras_pop_execute")
            else:
                ras_return_execute = ras_pop_execute

        # Misprediction detection logic
        # For conditional returns (e.g., OpenPOWER bclr):
        #   mispredict = ras_pop_execute && (!branch_taken || (prediction != target))
        # For unconditional returns (e.g., RISC-V jalr, MIPS jr):
        #   mispredict = ras_pop_execute && (prediction != target)
        return_branch_taken = self.analysis.return_branch_taken

        if return_branch_taken:
            # Conditional returns: must detect both branch-not-taken and target mismatch
            print(f"    Using conditional return logic with branch_taken: {return_branch_taken.id}")

            # Create !branch_taken
            branch_not_taken = Node('ras_branch_not_taken', data={
                'type': 'operation',
                'operator': '!',
                'name': 'ras_branch_not_taken',
                'display_name': 'Return branch not taken',
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(branch_not_taken)
            edge = Edge(return_branch_taken, branch_not_taken, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge)

            # Create (!branch_taken || prediction_mismatch)
            mispredict_or = Node('ras_mispredict_or', data={
                'type': 'operation',
                'operator': '||',
                'name': 'ras_mispredict_or',
                'display_name': 'Branch not taken OR target mismatch',
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(mispredict_or)
            edge1 = Edge(branch_not_taken, mispredict_or, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(mispredict_cmp, mispredict_or, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)

            # Create ras_pop_execute && mispredict_or
            mispredict_and = Node('ras_mispredict_and', data={
                'type': 'operation',
                'operator': '&&',
                'name': 'ras_mispredict_and',
                'display_name': 'RAS misprediction detected',
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(mispredict_and)
            edge1 = Edge(ras_return_execute, mispredict_and, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(mispredict_or, mispredict_and, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)

            edge = Edge(mispredict_and, ras_mispredict, data={'type': 'assignment'})
            self.graph.add_edge(edge)
            print(f"    Connected: ras_mispredict = ras_pop_execute && (!{return_branch_taken.id} || (ras_prediction != {jalr_target.id}))")
        else:
            # Unconditional returns: only check target mismatch
            mispredict_and = Node('ras_mispredict_and', data={
                'type': 'operation',
                'operator': '&&',
                'name': 'ras_mispredict_and',
                'display_name': 'RAS misprediction detected',
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(mispredict_and)

            edge1 = Edge(ras_return_execute, mispredict_and, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(mispredict_cmp, mispredict_and, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)

            edge = Edge(mispredict_and, ras_mispredict, data={'type': 'assignment'})
            self.graph.add_edge(edge)
            print(f"    Connected: ras_mispredict = ras_pop_execute && (ras_prediction != {jalr_target.id})")

        # =====================================================================
        # Modify control_hazard_flush to not flush on correct RAS predictions
        # =====================================================================
        # For architectures with CONDITIONAL returns (e.g., OpenPOWER bclr), we
        # cannot safely suppress the flush on correct predictions because:
        # 1. The instruction at return+4 (already fetched before RAS redirect)
        #    remains valid in the pipeline and would execute incorrectly
        # 2. If the conditional return is NOT taken, the RAS predicted taken
        #    but there's no recovery path to redirect to return+4
        # For these architectures, we skip both the flush modification and PC
        # prediction, keeping the original pipeline behavior intact. The RAS
        # stack is still maintained (push on calls) for future use.
        # =====================================================================
        has_conditional_returns = self.spec.return_branch_taken_node_id is not None
        if has_conditional_returns:
            print("  SKIPPING flush modification and PC prediction for conditional returns")
            print(f"    return_branch_taken_node_id = {self.spec.return_branch_taken_node_id}")
            print("    Original flush behavior preserved to avoid stale instruction execution")
            print("    RAS stack is maintained (push on calls) but prediction is not used")
            return

        # The control_hazard_flush currently treats JALR as unconditional flush.
        # We need to modify it so that:
        # - Non-return JALRs (jalr && !ras_pop) still flush
        # - Return JALRs only flush on misprediction (ras_mispredict)
        #
        # New JALR contribution = (jalr_enable && !ras_pop) || ras_mispredict
        # Since ras_mispredict = ras_pop && mismatch, this correctly handles:
        # - Non-return JALR: jalr_enable && !ras_pop → flush
        # - Return with correct prediction: ras_pop && !mismatch → no flush
        # - Return with wrong prediction: ras_pop && mismatch → flush
        # =====================================================================
        print("  Modifying control_hazard_flush for RAS integration...")

        # Find JALR's contribution to control_hazard_flush
        # The control hazard flush is typically an OR tree of flush conditions
        # We need to find and replace the JALR enable contribution
        jalr_enable_node = None
        for return_info in self.analysis.return_nodes:
            enable_id = return_info['spec'].enable_node_id
            jalr_enable_node = self.graph.nodes.get(enable_id)
            if jalr_enable_node:
                print(f"    Found JALR enable: {enable_id}")
                break

        if jalr_enable_node:
            # IMPORTANT: Use Execute-stage signals for flush, not Decode-stage!
            # Using Decode-stage signals causes the jalr instruction itself to be
            # invalidated by its own flush.
            #
            # We use the existing PIPE_Execute_jalr_enable_PIPE created by the
            # pipeline insertion pass, which is properly gated by stall/flush conditions.

            # Create: !ras_pop_execute (not a return at Execute stage)
            ras_pop_execute_not = Node('ras_pop_execute_not', data={
                'type': 'operation',
                'operator': '!',
                'name': 'ras_pop_execute_not',
                'display_name': 'Not a return instruction (Execute)',
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(ras_pop_execute_not)
            edge = Edge(ras_pop_execute, ras_pop_execute_not, data={'type': 'operand'})
            self.graph.add_edge(edge)

            # Find the existing pipelined enable for this return instruction
            # The pipeline insertion pass creates PIPE_Execute_{enable_id}_PIPE
            # For architectures without validity-gated enables, we also look for
            # the validity-gated version PIPE_Execute_{enable_id}_PIPE_valid_gated
            pipelined_enable_id = f'PIPE_Execute_{jalr_enable_node.id}_PIPE'
            validity_gated_enable_id = f'{pipelined_enable_id}_valid_gated'

            # First try the validity-gated version for non-validity-gated architectures
            ret_enable_execute = None
            if not return_enable_is_validity_gated:
                ret_enable_execute = self.graph.nodes.get(validity_gated_enable_id)
                if ret_enable_execute:
                    print(f"    Using existing {validity_gated_enable_id} for Execute-stage flush")

            if not ret_enable_execute:
                ret_enable_execute = self.graph.nodes.get(pipelined_enable_id)
                if ret_enable_execute:
                    print(f"    Using existing {pipelined_enable_id} for Execute-stage flush")
                    # For non-validity-gated architectures, gate by Execute validity
                    if not return_enable_is_validity_gated:
                        execute_valid = self.graph.nodes.get('PIPE_Execute_valid_PIPE')
                        if execute_valid:
                            ret_enable_execute_valid = Node('ret_enable_execute_valid', data={
                                'type': 'operation',
                                'operator': '&&',
                                'name': 'ret_enable_execute_valid',
                                'display_name': f'{jalr_enable_node.id} at Execute (validity-gated)',
                                'bit_width': 1,
                                'ras_component': True
                            })
                            self.graph.add_node(ret_enable_execute_valid)
                            edge1 = Edge(ret_enable_execute, ret_enable_execute_valid, data={'type': 'operand', 'position': 'left'})
                            edge2 = Edge(execute_valid, ret_enable_execute_valid, data={'type': 'operand', 'position': 'right'})
                            self.graph.add_edge(edge1)
                            self.graph.add_edge(edge2)
                            ret_enable_execute = ret_enable_execute_valid
                            print(f"    Created ret_enable_execute_valid (gated by PIPE_Execute_valid_PIPE)")
                else:
                    # Fallback: Create pipelined enable for Execute stage
                    print(f"    WARNING: {pipelined_enable_id} not found, creating pipelined enable")
                    ret_enable_execute = Node('ret_enable_execute', data={
                        'type': 'pipeline_register',
                        'name': 'ret_enable_execute',
                        'display_name': f'{jalr_enable_node.id} at Execute stage',
                        'bit_width': 1,
                        'ras_component': True,
                        'pipeline_stage': 'Execute',
                        'source_signal': jalr_enable_node.id
                    }, is_uarch_state=True, uarch_time=self.analysis.decode_stage + 1)
                    self.graph.add_node(ret_enable_execute)
                    edge = Edge(jalr_enable_node, ret_enable_execute, data={'type': 'pipeline_input', 'stages': 1})
                    self.graph.add_edge(edge)

            self.ras_nodes['ret_enable_execute'] = ret_enable_execute

            # Create: ret_enable_execute && !ras_pop_execute (non-return indirect jump at Execute)
            # This handles the case where the return instruction (e.g., JR) is used with a
            # non-link register (e.g., rs != 31), which is not a return and should still flush
            ret_non_return = Node('ret_non_return_flush', data={
                'type': 'operation',
                'operator': '&&',
                'name': 'ret_non_return_flush',
                'display_name': f'Non-return {jalr_enable_node.id} flush (Execute stage)',
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(ret_non_return)
            edge1 = Edge(ret_enable_execute, ret_non_return, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(ras_pop_execute_not, ret_non_return, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)

            # Create: (ret_enable && !ras_pop) || ras_mispredict
            #
            # This is the CORRECT flush logic for RAS:
            # - ret_non_return_flush: Return instruction executed WITHOUT RAS prediction
            #   (ras_pop_execute=0), so we need to flush and redirect to the computed target
            # - ras_mispredict: Return instruction executed WITH RAS prediction but the
            #   prediction was wrong (wrong target or branch not taken), so we need to flush
            #
            # When RAS prediction is CORRECT:
            # - The instruction in Decode is ALREADY at the correct return address
            # - No flush is needed! The prediction steered the fetch correctly.
            #
            # NOTE: We do NOT add a "redirect flush" term like we had before.
            # The previous ras_redirect_flush was wrong - it flushed even when
            # the prediction was correct, causing the return instruction to
            # invalidate itself.

            ret_ras_flush = Node('ret_ras_flush', data={
                'type': 'operation',
                'operator': '||',
                'name': 'ret_ras_flush',
                'display_name': f'{jalr_enable_node.id} flush with RAS',
                'bit_width': 1,
                'ras_component': True
            })
            self.graph.add_node(ret_ras_flush)
            edge1 = Edge(ret_non_return, ret_ras_flush, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(ras_mispredict, ret_ras_flush, data={'type': 'operand', 'position': 'right'})
            self.graph.add_edge(edge1)
            self.graph.add_edge(edge2)

            self.ras_nodes['ret_ras_flush'] = ret_ras_flush
            print(f"    Created ret_ras_flush = (non-return || mispredict)")

            # Now we need to find and replace this return instruction's contribution in control_hazard_flush
            # The flush signal is built as an OR tree. We need to find where the enable
            # (or a validity-gated version) feeds into the OR tree and replace it.
            self._replace_jalr_flush_contribution(jalr_enable_node, ret_ras_flush, control_hazard_flush)
        else:
            print("    Warning: Could not find JALR enable node for flush modification")

        # =====================================================================
        # Connect RAS prediction to PC prediction path
        # =====================================================================
        print("  Integrating RAS prediction into PC prediction path...")
        print(f"    Using predicted_pc: {predicted_pc.id}")
        print(f"    Using default_prediction: {default_prediction.id}")

        # Create a mux: ras_pop ? ras_top : default_prediction
        # This selects RAS prediction when a return is detected
        ras_predict_mux = Node('ras_predict_mux', data={
            'type': 'mux',
            'name': 'ras_predict_mux',
            'display_name': 'RAS Prediction Mux (ras_pop ? ras_top : pc+4)',
            'bit_width': self.spec.ras_width,
            'ras_component': True,
            'mux_select': 'ras_pop',
            'mux_true': 'ras_top',
            'mux_false': default_prediction.id
        })
        self.graph.add_node(ras_predict_mux)

        # Connect inputs to the mux
        edge1 = Edge(ras_pop, ras_predict_mux, data={'type': 'mux_select'})
        edge2 = Edge(ras_top, ras_predict_mux, data={'type': 'mux_input', 'condition': 'true'})
        edge3 = Edge(default_prediction, ras_predict_mux, data={'type': 'mux_input', 'condition': 'false'})
        self.graph.add_edge(edge1)
        self.graph.add_edge(edge2)
        self.graph.add_edge(edge3)

        # Rewire: disconnect default_prediction -> predicted_pc, connect ras_predict_mux -> predicted_pc
        edges_to_remove = []
        for edge_id, edge in self.graph.edges.items():
            if edge.source == default_prediction and edge.target == predicted_pc:
                edges_to_remove.append(edge_id)
        for edge_id in edges_to_remove:
            self.graph.remove_edge(edge_id)
            print(f"    Removed edge: {default_prediction.id} -> {predicted_pc.id}")

        # Connect the new mux to predicted_pc
        new_edge = Edge(ras_predict_mux, predicted_pc, data={'type': 'assignment'})
        self.graph.add_edge(new_edge)
        print(f"    Connected ras_predict_mux -> predicted_pc")
        print(f"    RAS prediction now used when ras_pop is active")

        self.ras_nodes['ras_predict_mux'] = ras_predict_mux

    def _replace_jalr_flush_contribution(self, jalr_enable: Node, new_jalr_flush: Node, control_hazard_flush: Node):
        """
        Replace JALR's contribution in the control_hazard_flush signal.

        The control_hazard_flush is built as an OR tree of flush conditions.
        We need to find where jalr_enable (or its validity-gated version) feeds
        into the OR tree and replace it with the new RAS-aware flush signal.

        Strategy: Trace backwards from control_hazard_flush to find which input
        comes from jalr_enable, then replace that input.
        """
        print("    Searching for JALR contribution in control hazard flush...")

        # First, find nodes that are connected to jalr_enable and also feed into the flush tree
        # These are typically validity-gated versions like "jalr_branch_taken_execute_valid_gated"
        jalr_derived_nodes = set()
        jalr_derived_nodes.add(jalr_enable.id)

        # BFS to find all nodes derived from jalr_enable (or jr_enable for MIPS)
        # Get the base enable pattern (e.g., 'jr', 'jalr', 'bclr') for matching pipeline registers
        # Handle validity-gated enables like 'bclr_enable_valid' -> pattern should be 'bclr'
        enable_pattern = jalr_enable.id.lower().replace('_enable', '').replace('_valid', '')
        print(f"    Looking for nodes derived from '{jalr_enable.id}' (pattern: '{enable_pattern}')")

        # If jalr_enable is a validity-gated version (ends with _valid), we need to find
        # the base enable and start BFS from there, since the flush tree uses the base enable
        base_enable = jalr_enable
        if jalr_enable.id.endswith('_valid'):
            # Find the base enable by looking at incoming edges
            for edge_id, edge in self.graph.edges.items():
                if edge.target == jalr_enable:
                    source = edge.source
                    # The base enable is the operand that ends with _enable (not _valid)
                    if source.id.endswith('_enable') and not source.id.endswith('_valid'):
                        base_enable = source
                        print(f"    Found base enable: {base_enable.id} (from validity-gated {jalr_enable.id})")
                        jalr_derived_nodes.add(base_enable.id)
                        break

        # Start BFS from both the validity-gated and base enables
        to_visit = [base_enable]
        if base_enable != jalr_enable:
            to_visit.append(jalr_enable)
        visited = set()
        while to_visit:
            node = to_visit.pop(0)
            if node.id in visited:
                continue
            visited.add(node.id)

            for edge_id, edge in self.graph.edges.items():
                if edge.source == node:
                    target = edge.target
                    # Skip nodes we just created (they have ras_component flag)
                    if target.data.get('ras_component'):
                        continue
                    target_name = target.id.lower()
                    # Follow paths that look like they're part of the flush tree
                    # Include: enable pattern (jr/jalr), valid, gated, taken, pipe (for pipeline registers)
                    if (enable_pattern in target_name or 'valid' in target_name or
                        'gated' in target_name or 'taken' in target_name or
                        'pipe' in target_name):
                        jalr_derived_nodes.add(target.id)
                        to_visit.append(target)

        print(f"    Found {len(jalr_derived_nodes)} nodes derived from JALR enable")

        # Now trace backwards from control_hazard_flush to find which input comes from a jalr-derived node
        # The flush is typically: flush_or_N = flush_or_N-1 || component
        # We need to find which OR node takes a jalr-derived input

        replaced = False
        nodes_to_check = [control_hazard_flush]
        checked = set()

        while nodes_to_check and not replaced:
            current = nodes_to_check.pop(0)
            if current.id in checked:
                continue
            checked.add(current.id)

            # Check incoming edges to this node
            for edge_id, edge in list(self.graph.edges.items()):
                if edge.target == current:
                    source = edge.source

                    # Check if this source is JALR-derived
                    if source.id in jalr_derived_nodes:
                        # Found it! Replace this edge
                        print(f"    Found JALR contribution: {source.id} -> {current.id}")
                        print(f"    Replacing with: {new_jalr_flush.id} -> {current.id}")

                        # Remove old edge properly (this also updates node's incoming/outgoing edges)
                        self.graph.remove_edge(edge_id)

                        # Add new edge from new_jalr_flush to current
                        new_edge = Edge(new_jalr_flush, current, data=edge.data.copy())
                        self.graph.add_edge(new_edge)
                        replaced = True
                        break

                    # If source is an OR node, we need to check its inputs too
                    if source.data.get('operator') == '||' or 'or' in source.id.lower():
                        nodes_to_check.append(source)

        if replaced:
            print("    Successfully replaced JALR contribution in control hazard flush")
        else:
            print("    Warning: Could not find JALR contribution to replace in flush tree")
            print("    JALR will still flush unconditionally - RAS only provides prediction")

    # =========================================================================
    # Phase 6: CLEANUP
    # =========================================================================

    def _cleanup_graph(self):
        """Remove any orphaned nodes and clean up the graph."""
        # For now, the RAS optimization doesn't create orphaned nodes
        # that need cleanup. The structure is additive.
        print("  No cleanup needed - RAS optimization is additive")

    # =========================================================================
    # Summary
    # =========================================================================

    def get_summary(self) -> str:
        """Generate a summary of the RAS optimization."""
        lines = []
        lines.append("\n" + "=" * 70)
        lines.append("RETURN ADDRESS STACK (RAS) OPTIMIZATION SUMMARY")
        lines.append("=" * 70)

        lines.append(f"\nConfiguration:")
        lines.append(f"  RAS depth: {self.spec.ras_depth} entries")
        lines.append(f"  RAS width: {self.spec.ras_width} bits")
        lines.append(f"  Link registers: {self.spec.link_registers}")

        if self.analysis:
            lines.append(f"\nCall patterns detected: {len(self.analysis.call_nodes)}")
            for i, call in enumerate(self.analysis.call_nodes):
                lines.append(f"  {i}: {call['spec'].enable_node_id}")

            lines.append(f"\nReturn patterns detected: {len(self.analysis.return_nodes)}")
            for i, ret in enumerate(self.analysis.return_nodes):
                lines.append(f"  {i}: {ret['spec'].enable_node_id}")

        lines.append(f"\nRAS nodes created:")
        for name, node in self.ras_nodes.items():
            lines.append(f"  {name}: {node.data.get('display_name', '')}")

        lines.append("\n" + "=" * 70)
        return "\n".join(lines)


def apply_return_address_stack(graph: ResourceGraph, spec: RASSpec) -> bool:
    """
    Convenience function to apply RAS optimization to a ResourceGraph.

    Args:
        graph: ResourceGraph to optimize
        spec: RAS specification

    Returns:
        True if RAS was successfully applied
    """
    ras = RASOptimization(graph, spec)
    success = ras.apply()

    if success:
        print(ras.get_summary())

    return success


if __name__ == "__main__":
    # Test RAS optimization
    import os
    import sys

    # Add project root to path
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from core.graph_merger import ResourceGraphMerger

    print("RETURN ADDRESS STACK OPTIMIZATION TEST")
    print("=" * 70)

    # Build a simple merged graph with jal and jalr
    rv32i_dir = os.path.join(project_root, "riscv32")

    merger = ResourceGraphMerger()
    merger.add_instruction('jal', os.path.join(rv32i_dir, 'jal.isa'))
    merger.add_instruction('jalr', os.path.join(rv32i_dir, 'jalr.isa'))
    merger.add_instruction('add', os.path.join(rv32i_dir, 'add.isa'))

    merged = merger.merge_graphs()
    merged.infer_uarch_time()

    print(f"\nMerged graph: {len(merged.nodes)} nodes, {len(merged.edges)} edges")

    # Apply RAS optimization
    ras_spec = RASSpec(
        call_specs=[
            CallSpec(
                enable_node_id='jal_enable',
                dest_reg_node_id='rd',
                return_addr_node_id='ret_addr'
            ),
            CallSpec(
                enable_node_id='jalr_enable',
                dest_reg_node_id='rd',
                return_addr_node_id='ret_addr'
            ),
        ],
        return_specs=[
            ReturnSpec(
                enable_node_id='jalr_enable',
                src_reg_node_id='rs1',
                dest_reg_node_id='rd'
            ),
        ],
        link_registers=[1, 5],
        ras_depth=8,
        ras_width=32
    )

    success = apply_return_address_stack(merged, ras_spec)

    if success:
        print(f"\nAfter RAS optimization: {len(merged.nodes)} nodes, {len(merged.edges)} edges")
    else:
        print("\nRAS optimization failed or not applicable")
