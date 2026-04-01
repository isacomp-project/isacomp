"""
Architectural Retiming Optimization for ResourceGraph.

This module implements architectural retiming, a technique that optimizes latency-constrained
circuits using "negative registers" (anti-registers) that counteract normal register latency.

Based on the work of Hassoun and Ebeling (1996), architectural retiming uses two main strategies:
1. Precomputation: Computing critical signals earlier in time by duplicating logic
2. Prediction: Predicting values and correcting on misprediction

This technique generalizes optimizations like branch prediction and bypassing, allowing
critical path signals to be computed early while preserving functional behavior.

Key features:
- Supports precomputation strategy (duplicate logic to run earlier)
- Supports prediction strategy (predict value with correction logic)
- Adds architectural state registers to hold early values
- Maintains functional correctness through prediction correction
- Works on any critical signal (ALU inputs, memory addresses, etc.)
"""

from typing import Dict, List, Set, Optional, Tuple
from core.resource_graph import ResourceGraph, Node, Edge
from copy import deepcopy


class ArchitecturalRetimingPass:
    """
    Implements architectural retiming using precomputation or prediction.

    The pass takes a target node (critical signal) and applies architectural
    retiming to compute or predict it earlier in the pipeline, potentially
    improving timing while maintaining functional correctness.
    """

    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.target_node: Optional[Node] = None
        self.strategy: str = "precomputation"  # or "prediction"
        self.depth: int = 1  # How many cycles early to compute
        self.precomputed_node: Optional[Node] = None
        self.predicted_node: Optional[Node] = None
        self.correction_logic: List[Node] = []

    def apply(self, target_node_id: str, strategy: str = "precomputation", depth: int = 1) -> bool:
        """
        Apply architectural retiming to a target node.

        Args:
            target_node_id: ID of the node to optimize (critical signal)
            strategy: Either "precomputation" or "prediction"
            depth: How many cycles early to compute/predict (must be <= target node's uarch_time)

        Returns:
            True if architectural retiming was successfully applied
        """
        print("\n" + "="*70)
        print("APPLYING ARCHITECTURAL RETIMING PASS")
        print("="*70)
        print(f"Target node: {target_node_id}")
        print(f"Strategy: {strategy}")
        print(f"Depth: {depth} cycle(s)")

        # Validate inputs
        if target_node_id not in self.graph.nodes:
            print(f"Error: Target node {target_node_id} not found in graph")
            return False

        if strategy not in ["precomputation", "prediction"]:
            print(f"Error: Invalid strategy '{strategy}'. Must be 'precomputation' or 'prediction'")
            return False

        if depth < 1:
            print(f"Error: Depth must be at least 1 cycle")
            return False

        self.target_node = self.graph.nodes[target_node_id]
        self.strategy = strategy
        self.depth = depth

        # Step 1: Analyze the target node and its dependencies
        if not self._analyze_target():
            print("Could not analyze target node - architectural retiming not applicable")
            return False

        # Step 2: Apply the chosen strategy
        if self.strategy == "precomputation":
            if not self._apply_precomputation():
                print("Precomputation strategy failed")
                return False
        elif self.strategy == "prediction":
            if not self._apply_prediction():
                print("Prediction strategy failed")
                return False

        # Step 3: Update timing information
        self.graph.infer_uarch_time()

        print("\nArchitectural retiming pass completed successfully")
        print("="*70)
        return True

    def _analyze_target(self) -> bool:
        """Analyze the target node to determine if architectural retiming is applicable."""
        print("\nStep 1: Analyzing target node...")

        # Get current timing
        current_time = self.target_node.uarch_time
        print(f"  Target node '{self.target_node.id}' at uarch_time: {current_time}")

        # Check if we can move it earlier
        if current_time is None:
            print(f"  Warning: Target node has no uarch_time, timing will be inferred")
        elif current_time < self.depth:
            print(f"  Error: Cannot move node {self.depth} cycles earlier (currently at cycle {current_time})")
            print(f"  Maximum depth for this node is {current_time} (can't go below cycle 0)")
            return False

        # Analyze dependencies
        input_nodes = []
        for edge in self.target_node.incoming_edges:
            if edge.data.get('type') in ['data', 'control', 'operand']:
                input_nodes.append(edge.source)

        print(f"  Found {len(input_nodes)} input dependencies")
        for inp in input_nodes:
            inp_time = inp.uarch_time if inp.uarch_time is not None else "unknown"
            print(f"    - {inp.id} (type: {inp.data.get('type')}, time: {inp_time})")

        return True

    def _apply_precomputation(self) -> bool:
        """
        Apply precomputation strategy: duplicate computation to run earlier.

        This creates a "negative register" by computing the target value earlier
        in the pipeline and storing it in an architectural state register.
        """
        print("\nStep 2: Applying precomputation strategy...")

        # Calculate target time for precomputed value
        current_time = self.target_node.uarch_time
        if current_time is None:
            # If no timing info, we'll let inference handle it
            target_time = 0
        else:
            target_time = max(0, current_time - self.depth)

        print(f"  Precomputing value at cycle {target_time} (original: {current_time})")

        # Step 2a: Duplicate the computation logic
        duplicated_nodes = self._duplicate_computation_tree(self.target_node, target_time)
        if not duplicated_nodes:
            print("  Error: Could not duplicate computation tree")
            return False

        print(f"  Duplicated {len(duplicated_nodes)} nodes for early computation")

        # Step 2b: Create architectural state register to hold precomputed value
        precomp_reg_id = f"{self.target_node.id}_precomputed"
        precomp_reg = Node(
            node_id=precomp_reg_id,
            data={'type': 'architectural_state', 'name': precomp_reg_id,
                  'description': f'Precomputed value of {self.target_node.id}'},
            is_arch_state=True,
            uarch_time=target_time
        )
        self.graph.add_node(precomp_reg)
        self.precomputed_node = precomp_reg

        print(f"  Created precomputation register: {precomp_reg_id}")

        # Step 2c: Connect duplicated computation to precomputation register
        # The root of the duplicated tree should write to the register
        if duplicated_nodes:
            root_dup = duplicated_nodes[0]  # First node is the root (target equivalent)
            assign_edge = Edge(
                source=root_dup,
                target=precomp_reg,
                data={'type': 'assignment', 'description': 'Store precomputed value'}
            )
            self.graph.add_edge(assign_edge)
            print(f"  Connected {root_dup.id} -> {precomp_reg_id}")

        # Step 2d: Create a read node for the precomputed value
        precomp_read_id = f"{self.target_node.id}_precomp_read"
        precomp_read = Node(
            node_id=precomp_read_id,
            data={'type': 'read_state', 'name': precomp_read_id},
            uarch_time=current_time
        )
        self.graph.add_node(precomp_read)

        # Connect read from precomputation register
        read_edge = Edge(
            source=precomp_reg,
            target=precomp_read,
            data={'type': 'state_read', 'description': 'Read precomputed value'}
        )
        self.graph.add_edge(read_edge)

        # Step 2e: Replace uses of original target with precomputed read
        self._replace_node_uses(self.target_node, precomp_read)

        print(f"  Replaced uses of {self.target_node.id} with precomputed value")

        return True

    def _apply_prediction(self) -> bool:
        """
        Apply prediction strategy: predict value early and correct on misprediction.

        This creates a "negative register" by predicting the target value earlier
        and adding correction logic when the prediction is wrong.
        """
        print("\nStep 2: Applying prediction strategy...")

        # Calculate target time for predicted value
        current_time = self.target_node.uarch_time
        if current_time is None:
            target_time = 0
        else:
            target_time = max(0, current_time - self.depth)

        print(f"  Predicting value at cycle {target_time} (actual: {current_time})")

        # Step 2a: Create predictor node (simple last-value predictor)
        predictor_id = f"{self.target_node.id}_predictor"
        predictor = Node(
            node_id=predictor_id,
            data={'type': 'operation', 'op': 'predict',
                  'description': f'Predicts value of {self.target_node.id}'},
            uarch_time=target_time
        )
        self.graph.add_node(predictor)

        print(f"  Created predictor node: {predictor_id}")

        # Step 2b: Create architectural state to hold last actual value
        last_value_id = f"{self.target_node.id}_last_value"
        last_value_reg = Node(
            node_id=last_value_id,
            data={'type': 'architectural_state', 'name': last_value_id,
                  'description': f'Last actual value of {self.target_node.id}'},
            is_arch_state=True,
            uarch_time=None  # Written at end of instruction
        )
        self.graph.add_node(last_value_reg)

        # Connect predictor to read last value
        read_last_edge = Edge(
            source=last_value_reg,
            target=predictor,
            data={'type': 'state_read', 'description': 'Read last value for prediction'}
        )
        self.graph.add_edge(read_last_edge)

        # Step 2c: Create predicted value register
        predicted_reg_id = f"{self.target_node.id}_predicted"
        predicted_reg = Node(
            node_id=predicted_reg_id,
            data={'type': 'architectural_state', 'name': predicted_reg_id,
                  'description': f'Predicted value of {self.target_node.id}'},
            is_arch_state=True,
            uarch_time=target_time
        )
        self.graph.add_node(predicted_reg)
        self.predicted_node = predicted_reg

        # Connect predictor to predicted register
        pred_assign_edge = Edge(
            source=predictor,
            target=predicted_reg,
            data={'type': 'assignment', 'description': 'Store predicted value'}
        )
        self.graph.add_edge(pred_assign_edge)

        print(f"  Created prediction register: {predicted_reg_id}")

        # Step 2d: Create misprediction detector
        mispredict_detect_id = f"{self.target_node.id}_mispredict_detect"
        mispredict_detect = Node(
            node_id=mispredict_detect_id,
            data={'type': 'operation', 'op': '!=',
                  'description': f'Detect misprediction of {self.target_node.id}'},
            uarch_time=current_time
        )
        self.graph.add_node(mispredict_detect)

        # Connect actual value and predicted value to detector
        actual_edge = Edge(
            source=self.target_node,
            target=mispredict_detect,
            data={'type': 'operand', 'operand_idx': 0}
        )
        self.graph.add_edge(actual_edge)

        pred_read_edge = Edge(
            source=predicted_reg,
            target=mispredict_detect,
            data={'type': 'operand', 'operand_idx': 1}
        )
        self.graph.add_edge(pred_read_edge)

        print(f"  Created misprediction detector: {mispredict_detect_id}")

        # Step 2e: Create correction mux (select predicted or actual based on misprediction)
        correction_mux_id = f"{self.target_node.id}_correction_mux"
        correction_mux = Node(
            node_id=correction_mux_id,
            data={'type': 'ternary_op', 'description': 'Correct mispredicted value'},
            uarch_time=current_time
        )
        self.graph.add_node(correction_mux)

        # Ternary: condition ? true_val : false_val
        # If mispredicted, use actual value; else use predicted value
        cond_edge = Edge(
            source=mispredict_detect,
            target=correction_mux,
            data={'type': 'ternary_condition'}
        )
        self.graph.add_edge(cond_edge)

        true_edge = Edge(
            source=self.target_node,
            target=correction_mux,
            data={'type': 'ternary_true'}
        )
        self.graph.add_edge(true_edge)

        false_edge = Edge(
            source=predicted_reg,
            target=correction_mux,
            data={'type': 'ternary_false'}
        )
        self.graph.add_edge(false_edge)

        print(f"  Created correction mux: {correction_mux_id}")

        # Step 2f: Replace uses of original target with correction mux
        self._replace_node_uses(self.target_node, correction_mux)

        # Step 2g: Update last_value register with actual value
        update_last_edge = Edge(
            source=self.target_node,
            target=last_value_reg,
            data={'type': 'assignment', 'description': 'Update last value'}
        )
        self.graph.add_edge(update_last_edge)

        print(f"  Replaced uses of {self.target_node.id} with corrected prediction")

        self.correction_logic = [mispredict_detect, correction_mux]

        return True

    def _duplicate_computation_tree(self, root: Node, target_time: int) -> List[Node]:
        """
        Duplicate the computation tree rooted at 'root' to run at 'target_time'.

        Returns list of duplicated nodes, with root equivalent first.
        """
        print(f"\n  Duplicating computation tree for {root.id}...")

        # For now, implement a simple single-node duplication
        # A full implementation would recursively duplicate the entire dependency tree

        # Create a duplicate of the root node
        dup_id = f"{root.id}_precomp_dup"
        dup_node = Node(
            node_id=dup_id,
            data=deepcopy(root.data),
            is_arch_state=False,
            is_uarch_state=False,
            uarch_time=target_time
        )
        self.graph.add_node(dup_node)

        # Copy incoming operand edges from original node
        for edge in root.incoming_edges:
            if edge.data.get('type') in ['operand', 'data', 'control']:
                # Create edge from same source to duplicated node
                dup_edge = Edge(
                    source=edge.source,
                    target=dup_node,
                    data=deepcopy(edge.data)
                )
                self.graph.add_edge(dup_edge)
                print(f"    Copied edge: {edge.source.id} -> {dup_id}")

        return [dup_node]

    def _replace_node_uses(self, old_node: Node, new_node: Node) -> None:
        """Replace all uses of old_node with new_node (except specific exclusions)."""
        edges_to_modify = []

        # Find all outgoing edges from old_node that we want to redirect
        for edge in list(old_node.outgoing_edges):
            # Don't replace edges we just created for correction logic
            if edge.target == self.precomputed_node:
                continue
            if edge.target in self.correction_logic:
                continue
            if edge.target.id.endswith('_last_value'):
                continue
            if edge.target.id == f"{old_node.id}_mispredict_detect":
                continue

            edges_to_modify.append(edge)

        # Redirect edges to new_node
        for edge in edges_to_modify:
            # Remove old edge
            edge.remove_from_nodes()
            self.graph.edges.pop(edge.id, None)

            # Create new edge from new_node to same target
            new_edge = Edge(
                source=new_node,
                target=edge.target,
                data=deepcopy(edge.data)
            )
            self.graph.add_edge(new_edge)


def apply_architectural_retiming(
    graph: ResourceGraph,
    target_node_id: str,
    strategy: str = "precomputation",
    depth: int = 1
) -> bool:
    """
    Apply architectural retiming optimization to a target node.

    Args:
        graph: The ResourceGraph to optimize
        target_node_id: ID of the critical signal to optimize
        strategy: Either "precomputation" or "prediction"
        depth: How many cycles early to compute/predict (must be <= target node's uarch_time)

    Returns:
        True if optimization was successfully applied

    Example:
        # Apply precomputation to compute ALU result 1 cycle early
        apply_architectural_retiming(graph, "alu_result", strategy="precomputation", depth=1)

        # Apply prediction to predict memory address 2 cycles early
        # (assumes mem_addr is at uarch_time >= 2)
        apply_architectural_retiming(graph, "mem_addr", strategy="prediction", depth=2)
    """
    pass_obj = ArchitecturalRetimingPass(graph)
    return pass_obj.apply(target_node_id, strategy, depth)


def get_retimeable_nodes(graph: ResourceGraph) -> Dict[str, Dict[str, any]]:
    """
    Identify nodes in the graph that are good candidates for architectural retiming.

    Returns a dictionary mapping node IDs to their properties:
    - uarch_time: Current cycle time
    - can_precompute: Whether precomputation is feasible
    - can_predict: Whether prediction is feasible
    - max_depth: Maximum cycles it can be moved earlier

    Good candidates are typically:
    - Operation nodes (not state)
    - Nodes with sufficient uarch_time to move earlier
    - Nodes on critical paths
    """
    candidates = {}

    for node_id, node in graph.nodes.items():
        # Skip state nodes
        if node.is_arch_state or node.is_uarch_state:
            continue

        # Skip nodes without timing info
        if node.uarch_time is None:
            continue

        # Skip early nodes
        if node.uarch_time < 1:
            continue

        # This node is a candidate
        candidates[node_id] = {
            'uarch_time': node.uarch_time,
            'type': node.data.get('type', 'unknown'),
            'can_precompute': True,  # Most operations can be precomputed
            'can_predict': True,  # Most values can be predicted
            'max_depth': node.uarch_time  # Can move up to cycle 0
        }

    return candidates
