"""
Not-Taken Branch Prediction Pass for ResourceGraph.

This module implements a static not-taken branch prediction optimization that
predicts branches as not-taken, allowing instruction fetch to proceed speculatively.
When a misprediction is detected, instructions in the pipeline are flushed.

Key features:
- Predicts branches as not-taken (computes PC+offset early in pipeline)
- Adds instruction validity tracking to each pipeline stage
- Implements pipeline flush on misprediction
- Prevents invalid instructions from updating architectural state

This is one of several possible branch prediction strategies. Other strategies
(e.g., taken prediction, dynamic prediction) can be implemented as separate passes.
"""

from typing import Dict, List, Set, Optional, Tuple
from core.resource_graph import ResourceGraph, Node, Edge
from core.mux_utils import MuxBuilder, MuxType


class BranchPredictionNotTakenPass:
    """
    Implements static not-taken branch prediction with pipeline flush.

    The pass identifies PC update muxes (which select between branch target
    and sequential PC) and modifies them to:
    1. Predict not-taken (use PC+offset early)
    2. Add early prediction logic in pipeline stage 0
    3. Add validity bits to track instruction validity through pipeline
    4. Add flush logic when misprediction is detected
    5. Gate architectural state updates with validity signals
    """

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.validity_nodes: Dict[int, Node] = {}  # uarch_time -> validity node
        self.pc_node: Optional[Node] = None
        self.pc_mux: Optional[Node] = None
        self.not_taken_input: Optional[Node] = None
        self.taken_input: Optional[Node] = None
        self.branch_condition: Optional[Node] = None
        self.pc_width: Optional[int] = None  # Must be determined from pc_rd node

    def apply(self) -> bool:
        """
        Apply branch prediction optimization to the graph.

        Returns:
            True if branch prediction was successfully applied
        """
        print("\n" + "="*70)
        print("APPLYING BRANCH PREDICTION PASS")
        print("="*70)

        # Step 1: Find PC node and its assignment mux
        if not self._find_pc_and_mux():
            print("Could not find PC node with branch mux - branch prediction not applicable")
            return False

        # Step 2: Analyze the PC mux to identify branch patterns
        if not self._analyze_branch_pattern():
            print("Could not identify branch pattern - branch prediction not applicable")
            return False

        # Step 3: Create validity tracking for each pipeline stage
        self._create_validity_tracking()

        # Step 4: Add early PC prediction (not-taken)
        self._add_early_prediction()

        # Step 5: Add misprediction detection and flush logic
        self._add_flush_logic()

        # Step 6: Gate architectural state updates with validity
        self._gate_arch_state_updates()

        # Step 7: Update timing
        self.graph.infer_uarch_time()

        print("\nBranch prediction pass completed successfully")
        print("="*70)
        return True

    def _find_pc_and_mux(self) -> bool:
        """Find the PC node and its assignment mux or ternary."""
        print("\nStep 1: Finding PC node and assignment mux/ternary...")

        # Look for pc_wr node (write node after splitting)
        pc_candidates = ['pc_wr', 'pc']

        for pc_id in pc_candidates:
            if pc_id in self.graph.nodes:
                self.pc_node = self.graph.nodes[pc_id]
                print(f"  Found PC node: {pc_id}")
                break

        if not self.pc_node:
            return False

        # Get PC width from pc_rd node (the read port has the bit_width metadata)
        pc_rd_node = self.graph.nodes.get('pc_rd')
        if pc_rd_node and pc_rd_node.data.get('bit_width'):
            self.pc_width = pc_rd_node.data['bit_width']
            print(f"  PC width: {self.pc_width} bits")

        # Find the mux or ternary that feeds the PC
        # PC should have incoming assignment edges from a mux or ternary_op
        for edge in self.pc_node.incoming_edges:
            if edge.data.get('type') == 'assignment':
                source = edge.source
                source_type = source.data.get('type')
                if source_type == 'multiplexer':
                    self.pc_mux = source
                    print(f"  Found PC assignment mux: {self.pc_mux.id}")
                    return True
                elif source_type == 'ternary_op':
                    # Ternary operator acts like a 2-input mux
                    # We'll treat it as our "mux" for branch prediction purposes
                    self.pc_mux = source
                    print(f"  Found PC assignment ternary: {self.pc_mux.id}")
                    return True

        return False

    def _analyze_branch_pattern(self) -> bool:
        """
        Analyze the PC mux/ternary to identify branch vs sequential PC inputs.

        Branch muxes typically have:
        - One input for sequential PC (e.g., PC+4, PC+2)
        - One or more inputs for branch targets (e.g., PC+offset, computed target)

        Ternaries have:
        - A condition
        - A true branch (typically the branch target)
        - A false branch (typically the sequential PC)
        """
        print("\nStep 2: Analyzing branch pattern...")

        # Check if this is a ternary operator
        if self.pc_mux.data.get('type') == 'ternary_op':
            return self._analyze_ternary_pattern()

        # Otherwise, it's a multiplexer
        return self._analyze_mux_pattern()

    def _analyze_ternary_pattern(self) -> bool:
        """Analyze a ternary operator for branch prediction."""
        print("  Analyzing ternary operator...")

        # Find the true and false branches of the ternary
        ternary_condition = None
        ternary_true = None
        ternary_false = None

        for edge in self.pc_mux.incoming_edges:
            edge_type = edge.data.get('type', '')
            if edge_type == 'ternary_condition':
                ternary_condition = edge.source
            elif edge_type == 'ternary_true':
                ternary_true = edge.source
            elif edge_type == 'ternary_false':
                ternary_false = edge.source

        if not all([ternary_condition, ternary_true, ternary_false]):
            print("  Error: Ternary operator missing condition, true, or false branch")
            return False

        # For branch prediction:
        # - False branch is typically the not-taken path (PC+4, PC+2)
        # - True branch is typically the taken path (branch target)
        self.not_taken_input = ternary_false
        self.taken_input = ternary_true
        self.branch_condition = ternary_condition

        print(f"  Ternary condition: {ternary_condition.id}")
        print(f"  Not-taken path (false): {ternary_false.id} - {ternary_false.data.get('display_name', '')}")
        print(f"  Taken path (true): {ternary_true.id} - {ternary_true.data.get('display_name', '')}")

        return True

    def _analyze_mux_pattern(self) -> bool:
        """Analyze a multiplexer for branch prediction."""
        # Collect mux inputs (both regular and default inputs)
        mux_inputs = []
        default_input = None

        for edge in self.pc_mux.incoming_edges:
            edge_type = edge.data.get('type')
            if edge_type == 'mux_input':
                mux_inputs.append({
                    'edge': edge,
                    'source': edge.source,
                    'index': edge.data.get('input_index', 0),
                    'instruction': edge.data.get('source_instruction', 'unknown')
                })
            elif edge_type == 'mux_default_input':
                # Flat mux structure uses mux_default_input for the default value
                default_input = edge.source
                print(f"  Found default input: {default_input.id}")

        mux_inputs.sort(key=lambda x: x['index'])

        print(f"  PC mux has {len(mux_inputs)} conditional inputs:")
        for inp in mux_inputs:
            source = inp['source']
            print(f"    Input {inp['index']} ({inp['instruction']}): {source.id} - {source.data.get('display_name', '')}")

        # Need at least 1 conditional input (branches/jumps) plus a default
        if len(mux_inputs) < 1:
            print("  Error: PC mux needs at least 1 conditional input for branch prediction")
            return False

        # For not-taken prediction:
        # - If there's a default input, use it (this is the sequential PC path)
        # - Otherwise, use heuristics based on mux input names
        if self.not_taken_input is None:
            # Only auto-detect if not explicitly set
            if default_input:
                self.not_taken_input = default_input
            elif mux_inputs:
                # Fallback: look for a (pc + 4) style input
                for inp in mux_inputs:
                    if '(pc + 4)' in inp['source'].id or 'pc_add_4' in inp['source'].id:
                        self.not_taken_input = inp['source']
                        break
                if not self.not_taken_input:
                    # Last resort: use first input
                    self.not_taken_input = mux_inputs[0]['source']

        # For taken path, find a representative branch/jump target
        if self.taken_input is None:
            # Only auto-detect if not explicitly set
            for inp in mux_inputs:
                source = inp['source']
                # Check if this looks like a branch target
                # (Contains operations like add with offset, or is a ternary)
                if source.data.get('type') in ['operation', 'ternary_op']:
                    self.taken_input = source
                    break

            if not self.taken_input and mux_inputs:
                # Fallback: use last input
                self.taken_input = mux_inputs[-1]['source']

        print(f"  Identified not-taken path: {self.not_taken_input.id if self.not_taken_input else 'None'}")
        print(f"  Identified taken path: {self.taken_input.id if self.taken_input else 'None'}")

        # Try to find the branch condition
        # Look for mux select signals
        for edge in self.pc_mux.incoming_edges:
            if edge.data.get('type') == 'mux_select':
                # This is a select signal - could be the branch condition
                condition = edge.data.get('condition')
                if condition:
                    print(f"  Found branch condition: {condition}")
                    # For now, we'll track that there's a condition but won't
                    # try to parse it - actual branch resolution happens later

        return True

    def _create_validity_tracking(self):
        """
        Create validity tracking nodes for each pipeline stage.

        Validity bits indicate whether an instruction in a pipeline stage
        is valid or should be treated as a NOP (due to flush).
        """
        print("\nStep 3: Creating validity tracking...")

        max_time = self.graph.get_max_uarch_time()

        for time in range(max_time + 1):
            validity_id = f"stage_{time}_valid"
            validity_data = {
                'type': 'validity_bit',
                'name': validity_id,
                'display_name': f"Stage {time} validity",
                'uarch_stage': time,
                'bit_width': 1,
                'description': f"Indicates if instruction in stage {time} is valid"
            }

            validity_node = Node(validity_id, validity_data, is_uarch_state=True, uarch_time=time)
            # Set pipe_time to match uarch_time for validity tracking
            validity_node.pipe_time = time
            self.graph.add_node(validity_node)
            self.validity_nodes[time] = validity_node
            print(f"  Created validity node for stage {time}: {validity_id}")

    def _add_early_prediction(self):
        """
        Add early PC prediction logic.

        In not-taken prediction, the predicted next PC is simply (PC + 4).
        This is computed early in stage 0, allowing speculative fetch to begin
        before the branch resolves.
        """
        print("\nStep 4: Adding early PC prediction (not-taken)...")

        # Find the (pc + 4) node - this is the not-taken prediction
        pc_plus_4 = self.graph.nodes.get("(pc + 4)")
        if not pc_plus_4:
            print("  Error: Could not find (pc + 4) node!")
            return

        # Create predicted PC node that aliases (pc + 4)
        # This is computed at stage 0 for early prediction
        predicted_pc_id = "predicted_pc"
        predicted_pc_data = {
            'type': 'var',
            'name': predicted_pc_id,
            'display_name': "Predicted PC (not-taken)",
            'description': "Predicted next PC = PC + 4 (not-taken speculation)",
        }
        if self.pc_width:
            predicted_pc_data['bit_width'] = self.pc_width

        predicted_pc_node = Node(predicted_pc_id, predicted_pc_data, uarch_time=0)
        self.graph.add_node(predicted_pc_node)

        # Connect (pc + 4) to predicted_pc
        # predicted_pc is just an alias/wire that holds the speculative next PC
        pred_edge = Edge(pc_plus_4, predicted_pc_node, data={
            'type': 'assignment',
            'description': 'Speculative not-taken prediction'
        })
        self.graph.add_edge(pred_edge)

        print(f"  Created predicted PC node: {predicted_pc_id}")
        print(f"  Predicted PC = (pc + 4) for not-taken speculation")

        # CRITICAL: Connect predicted_pc to the PC node so it actually gets used
        # Currently pc_wr gets its value from pc_wr_mux (late arriving)
        # We need to change it to use predicted_pc by default

        # Find the edge from pc_mux to pc_node and redirect it through predicted_pc
        mux_to_pc_edge = None
        for edge in self.pc_node.incoming_edges:
            if edge.source == self.pc_mux:
                mux_to_pc_edge = edge
                break

        if mux_to_pc_edge:
            # Remove the direct edge from mux to PC
            self.graph.remove_edge(mux_to_pc_edge.id)  # Pass edge ID string, not Edge object
            print(f"  Removed direct edge from {self.pc_mux.id} to {self.pc_node.id}")

            # Create a recovery mux that selects between:
            # - predicted_pc (normal case - not-taken prediction)
            # - pc_mux (misprediction recovery - branch was actually taken)
            recovery_mux_id = "pc_recovery_mux"
            recovery_mux_data = {
                'type': 'ternary_op',
                'name': recovery_mux_id,
                'display_name': "PC recovery mux (predicted vs actual)",
                'operator': '?:',
                'description': 'Selects predicted PC normally, actual target on misprediction',
            }
            if self.pc_width:
                recovery_mux_data['bit_width'] = self.pc_width

            # Recovery mux operates at stage 0 for fast correction
            recovery_mux_node = Node(recovery_mux_id, recovery_mux_data, uarch_time=0)
            self.graph.add_node(recovery_mux_node)

            # Connect predicted_pc as the "not mispredicted" path (ternary false)
            pred_edge = Edge(predicted_pc_node, recovery_mux_node, data={
                'type': 'ternary_false',
                'description': 'Normal (predicted) PC'
            })
            self.graph.add_edge(pred_edge)

            # Connect pc_mux as the "mispredicted" path (ternary true)
            actual_edge = Edge(self.pc_mux, recovery_mux_node, data={
                'type': 'ternary_true',
                'description': 'Actual PC on misprediction'
            })
            self.graph.add_edge(actual_edge)

            # We'll connect the condition (misprediction signal) in _add_flush_logic
            # Store the recovery mux for later
            self.recovery_mux = recovery_mux_node

            # Connect recovery mux to PC
            recovery_to_pc_edge = Edge(recovery_mux_node, self.pc_node, data={
                'type': 'assignment',
                'description': 'PC update with prediction and recovery'
            })
            self.graph.add_edge(recovery_to_pc_edge)

            print(f"  Created recovery mux: {recovery_mux_id}")
            print(f"  Connected {predicted_pc_id} -> {recovery_mux_id} -> {self.pc_node.id}")
        else:
            print(f"  Warning: Could not find edge from mux to PC, predicted_pc not connected!")
            self.recovery_mux = None

    def _add_flush_logic(self):
        """
        Connect the existing control hazard flush signal to the PC recovery mux.

        In a not-taken prediction scheme:
        - Misprediction occurs when a branch is actually taken or a jump occurs
        - The control_hazard_flush signal already detects this condition
        - We just need to connect it to the PC recovery mux
        """
        print("\nStep 5: Connecting control hazard flush to PC recovery mux...")

        # Find the existing control_hazard_flush signal (created by HazardResolver)
        control_hazard_flush = self.graph.nodes.get("control_hazard_flush")

        if not control_hazard_flush:
            print("  Warning: control_hazard_flush node not found!")
            print("  Branch prediction requires control hazard handling to be applied first")
            return

        print(f"  Found control_hazard_flush signal (created by HazardResolver)")

        # Connect control_hazard_flush to the PC recovery mux condition
        # When flush is active (branch taken/jump), select actual PC from pc_mux
        # When flush is inactive (not-taken prediction correct), use predicted_pc
        if hasattr(self, 'recovery_mux') and self.recovery_mux:
            recovery_cond_edge = Edge(control_hazard_flush, self.recovery_mux, data={
                'type': 'ternary_condition',
                'description': 'Control hazard (misprediction) triggers PC recovery'
            })
            self.graph.add_edge(recovery_cond_edge)
            print(f"  Connected control_hazard_flush to PC recovery mux condition")
        else:
            print(f"  Warning: recovery_mux not found, could not connect flush signal")

        # Note: Pipeline flushing (invalidating instructions in flight) is already
        # handled by the HazardResolver via control_hazard_flush and validity signals.
        # No additional flush logic needed here.

    def _gate_arch_state_updates(self):
        """
        Gate all architectural state updates with validity signals.

        Prevents invalid (flushed) instructions from modifying architectural state.
        Each write to architectural state is gated by the validity bit of its
        pipeline stage.
        """
        print("\nStep 6: Gating architectural state updates with validity...")

        gated_count = 0

        # Find all architectural state write nodes
        for node in list(self.graph.nodes.values()):
            if not node.is_arch_state:
                continue

            # Skip if this is a read node
            if node.id.endswith('_rd'):
                continue

            # Check if this node receives write edges
            # - assignment edges for regular state nodes
            # - write_data/write_address edges for memory_write_port nodes
            has_writes = any(e.data.get('type') in ['assignment', 'write_data', 'write_address']
                           for e in node.incoming_edges)
            if not has_writes:
                continue

            # Determine the uarch_time of this write
            write_time = node.uarch_time if node.uarch_time is not None else 0

            # Get the validity node for this stage
            if write_time in self.validity_nodes:
                validity_node = self.validity_nodes[write_time]

                # Add validity check edge
                validity_edge = Edge(validity_node, node, data={
                    'type': 'validity_check',
                    'description': f"Gate write to {node.id} with stage {write_time} validity"
                })
                self.graph.add_edge(validity_edge)

                gated_count += 1
                print(f"  Gated {node.id} with stage {write_time} validity")

        print(f"  Total architectural state nodes gated: {gated_count}")

    def get_summary(self) -> str:
        """Generate a summary of the branch prediction optimization."""
        lines = []
        lines.append("\n" + "="*70)
        lines.append("BRANCH PREDICTION PASS SUMMARY")
        lines.append("="*70)

        lines.append(f"\nPC Node: {self.pc_node.id if self.pc_node else 'None'}")
        lines.append(f"PC Mux: {self.pc_mux.id if self.pc_mux else 'None'}")
        lines.append(f"Not-taken path: {self.not_taken_input.id if self.not_taken_input else 'None'}")
        lines.append(f"Taken path: {self.taken_input.id if self.taken_input else 'None'}")

        lines.append(f"\nPipeline Stages with Validity Tracking: {len(self.validity_nodes)}")
        for time, node in sorted(self.validity_nodes.items()):
            lines.append(f"  Stage {time}: {node.id}")

        # Count gated arch state nodes
        gated_nodes = [n for n in self.graph.nodes.values()
                      if any(e.data.get('type') == 'validity_check' for e in n.incoming_edges)]
        lines.append(f"\nArchitectural State Nodes Gated: {len(gated_nodes)}")
        for node in gated_nodes:
            lines.append(f"  {node.id}")

        # Find prediction-related nodes
        prediction_nodes = [n for n in self.graph.nodes.values()
                          if n.data.get('type') in ['misprediction_detector', 'flush_controller']]
        lines.append(f"\nBranch Prediction Components: {len(prediction_nodes)}")
        for node in prediction_nodes:
            lines.append(f"  {node.id}: {node.data.get('display_name', '')}")

        lines.append("\n" + "="*70)
        return "\n".join(lines)


def apply_branch_prediction_not_taken(graph: ResourceGraph,
                                      pc_node_id: Optional[str] = None,
                                      pc_mux_id: Optional[str] = None,
                                      not_taken_input_id: Optional[str] = None,
                                      taken_input_id: Optional[str] = None) -> bool:
    """
    Convenience function to apply not-taken branch prediction to a ResourceGraph.

    Args:
        graph: ResourceGraph to optimize
        pc_node_id: Optional explicit PC node ID (auto-detected if None)
        pc_mux_id: Optional explicit PC mux/ternary ID (auto-detected if None)
        not_taken_input_id: Optional explicit not-taken input node ID (auto-detected if None)
        taken_input_id: Optional explicit taken input node ID (auto-detected if None)

    Returns:
        True if branch prediction was successfully applied
    """
    bp_pass = BranchPredictionNotTakenPass(graph)

    # Override auto-detection if explicit IDs provided
    if pc_node_id and pc_node_id in graph.nodes:
        bp_pass.pc_node = graph.nodes[pc_node_id]
    if pc_mux_id and pc_mux_id in graph.nodes:
        bp_pass.pc_mux = graph.nodes[pc_mux_id]
    if not_taken_input_id and not_taken_input_id in graph.nodes:
        bp_pass.not_taken_input = graph.nodes[not_taken_input_id]
    if taken_input_id and taken_input_id in graph.nodes:
        bp_pass.taken_input = graph.nodes[taken_input_id]

    success = bp_pass.apply()

    if success:
        print(bp_pass.get_summary())

    return success


if __name__ == "__main__":
    # Test branch prediction pass
    print("BRANCH PREDICTION PASS TEST")
    print("="*70)

    # Test with a branch instruction
    graph = ResourceGraph.from_isa_file('isa/riscv32/beq.isa')

    # First merge it with another instruction to create the mux
    from core.graph_merger import ResourceGraphMerger
    merger = ResourceGraphMerger()
    merger.add_instruction('beq', 'isa/riscv32/beq.isa')
    merger.add_instruction('add', 'isa/riscv32/add.isa')
    merged = merger.merge_graphs()

    print(f"\nOriginal merged graph: {merged}")
    print(f"Max uarch_time: {merged.get_max_uarch_time()}")

    # Apply branch prediction
    success = apply_branch_prediction(merged)

    if success:
        print(f"\nAfter branch prediction: {merged}")
        print(f"New max uarch_time: {merged.get_max_uarch_time()}")
    else:
        print("\nBranch prediction optimization not applicable to this graph")
