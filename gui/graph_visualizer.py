#!/usr/bin/env python3
"""
Interactive GUI for ResourceGraph visualization and optimization.

This provides a graphical interface to:
- Load and display ResourceGraphs
- Move nodes interactively
- Inspect node/edge properties
- Apply optimization strategies
- Compare before/after results
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import math
import threading
from typing import Dict, List, Tuple, Optional, Set, Any
from dataclasses import dataclass, field
import traceback
from datetime import datetime

from core.resource_graph import ResourceGraph, Node, Edge
from core.graph_merger import merge_instructions
from opt.pipeline.pipelining_optimization import apply_pipelining_optimization
from gui.graph_layout import GraphLayoutEngine, GraphLayoutOptimizer, Point
from opt.sharing.operation_sharing import apply_operation_sharing, SharingMode
from opt.sharing.unroll_shared_operations import unroll_shared_operations
from opt.memory.memory_sharing import apply_register_file_sharing
from opt.temporal.operation_serialization import apply_operation_serialization, SerializationSpec
from opt.temporal.operation_parallelization import parallelize_serialized_operations
from opt.fetch.branch_prediction_not_taken import apply_branch_prediction_not_taken
from opt.retiming_optimization import apply_retiming_forward, apply_retiming_backward, get_retimeable_registers
from opt.architectural_retiming import apply_architectural_retiming, get_retimeable_nodes
from backends.verilog import generate_verilog
from opt.ooo.register_renaming_optimization import apply_register_renaming, RegisterRenamingSpec
from opt.ooo.register_renaming_optimization import has_register_renaming, get_renamed_resources
from opt.memory.memory_access_transform import MemoryAccessTransform, MemoryAccessTransformSpec


@dataclass
class GraphLayout:
    """Layout information for a ResourceGraph."""
    node_positions: Dict[str, Point]
    canvas_width: int = 800
    canvas_height: int = 600


@dataclass
class OptimizationTreeNode:
    """Represents a node in the optimization tree."""
    graph: ResourceGraph
    label: str
    parent: Optional['OptimizationTreeNode'] = None
    children: List['OptimizationTreeNode'] = field(default_factory=list)
    optimization_name: Optional[str] = None
    optimization_params: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.now)
    tree_item_id: Optional[str] = None  # ID in the treeview widget

    def add_child(self, child: 'OptimizationTreeNode') -> 'OptimizationTreeNode':
        """Add a child node and set its parent reference."""
        child.parent = self
        self.children.append(child)
        return child

    def get_path_from_root(self) -> List['OptimizationTreeNode']:
        """Get the path from root to this node."""
        path = []
        current = self
        while current is not None:
            path.insert(0, current)
            current = current.parent
        return path


class OptimizationStrategy:
    """Represents an optimization strategy that can be applied."""

    def __init__(self, name: str, description: str, apply_function, parameters: List[Dict]):
        self.name = name
        self.description = description
        self.apply_function = apply_function
        self.parameters = parameters  # List of parameter specs: {'name': str, 'type': str, 'default': any}


class ResourceGraphVisualizer:
    """Main GUI application for ResourceGraph visualization."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ResourceGraph Visualizer")
        self.root.geometry("1200x800")

        # Graph data
        self.current_graph: Optional[ResourceGraph] = None
        self.graph_layout: Optional[GraphLayout] = None
        self.selected_nodes: Set[str] = set()
        self.selected_edges: Set[str] = set()

        # GUI state
        self.dragging_node: Optional[str] = None
        self.drag_start_pos: Optional[Tuple[float, float]] = None

        # Multi-stage pipelining state
        self.multistage_panel = None
        self.multistage_panel_visible = False
        self.multistage_edges_per_stage = {}  # stage_index -> list of edge_ids
        self.line_drag_mode = False  # Line drag selection mode
        self.line_drag_start = None  # Start point of line drag
        self.line_drag_temp_line = None  # Temporary line on canvas

        # Optimization tree state
        self.tree_root: Optional[OptimizationTreeNode] = None
        self.current_tree_node: Optional[OptimizationTreeNode] = None
        self.tree_visible: bool = True
        self.right_visible: bool = True

        # Canvas items
        self.node_items: Dict[str, int] = {}  # node_id -> canvas_item_id
        self.edge_items: Dict[str, int] = {}  # edge_id -> canvas_item_id
        self.node_labels: Dict[str, int] = {}  # node_id -> label_canvas_item_id

        # Layout engines
        self.layout_engine = GraphLayoutEngine(800, 600)
        self.layout_optimizer = GraphLayoutOptimizer()

        # Optimization strategies
        self.optimization_strategies = self._create_optimization_strategies()

        self._create_gui()

    def _create_gui(self):
        """Create the main GUI layout."""

        # Create main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create toolbar
        toolbar_frame = ttk.Frame(main_frame)
        toolbar_frame.pack(fill=tk.X, pady=(0, 5))

        # Import dropdown menu
        import_button = tk.Menubutton(toolbar_frame, text="Import ▼", relief=tk.RAISED, borderwidth=1)
        import_button.pack(side=tk.LEFT, padx=(0, 5))
        import_menu = tk.Menu(import_button, tearoff=0)
        import_button.config(menu=import_menu)

        import_menu.add_command(label="ISA/ILA File(s) (.isa, .json)", command=self.load_isa_files)
        import_menu.add_command(label="SAIL File(s) (.sail)", command=self.load_sail_files)
        import_menu.add_command(label="Verilog File (.v, .sv)", command=self.load_verilog_file)
        import_menu.add_separator()
        import_menu.add_command(label="ResourceGraph (.rgraph)", command=self.load_graph)

        # Export dropdown menu
        export_button = tk.Menubutton(toolbar_frame, text="Export ▼", relief=tk.RAISED, borderwidth=1)
        export_button.pack(side=tk.LEFT, padx=(0, 5))
        export_menu = tk.Menu(export_button, tearoff=0)
        export_button.config(menu=export_menu)

        export_menu.add_command(label="ResourceGraph (.rgraph)", command=self.save_graph)
        export_menu.add_command(label="Verilog (.v)", command=self.export_verilog)

        # Layout selection
        layout_frame = ttk.Frame(toolbar_frame)
        layout_frame.pack(side=tk.LEFT, padx=(0, 5))

        ttk.Label(layout_frame, text="Layout:").pack(side=tk.LEFT)
        self.layout_var = tk.StringVar(value="Smart ⚙")

        # Layout options with complexity indicators (⚡=fast, ⚙=medium, ⏱=slow)
        layout_options = [
            "Smart ⚙",
            "Architectural ⚡",
            "Pipeline Viewer ⚡",
            "Timeline ⚡",
            "Hierarchical ⚡",
            "Force-Directed ⏱",
            "Circular ⚡",
            "Grid ⚡",
            "Pipeline ⚡",
            "Layered ⚙"
        ]

        layout_combo = ttk.Combobox(layout_frame, textvariable=self.layout_var,
                                   values=layout_options,
                                   state="readonly", width=20)
        layout_combo.pack(side=tk.LEFT, padx=(5, 0))
        layout_combo.bind('<<ComboboxSelected>>', self.on_layout_changed)

        # Display options
        display_frame = ttk.Frame(toolbar_frame)
        display_frame.pack(side=tk.LEFT, padx=(5, 5))

        self.show_timing_var = tk.BooleanVar(value=False)
        timing_checkbox = ttk.Checkbutton(display_frame, text="Show Timing",
                                        variable=self.show_timing_var,
                                        command=self.on_display_option_changed)
        timing_checkbox.pack(side=tk.LEFT)

        self.symbolic_operators_var = tk.BooleanVar(value=False)
        symbolic_checkbox = ttk.Checkbutton(display_frame, text="Symbolic Operators",
                                          variable=self.symbolic_operators_var,
                                          command=self.on_display_option_changed)
        symbolic_checkbox.pack(side=tk.LEFT, padx=(5, 0))

        ttk.Button(toolbar_frame, text="Clear Selection", command=self.clear_selection).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(toolbar_frame, text="Cleanup Graph", command=self.cleanup_graph).pack(side=tk.LEFT, padx=(0, 5))

        # Create main content area with PanedWindow for resizable panels
        content_paned = tk.PanedWindow(main_frame, orient=tk.HORIZONTAL, sashwidth=5)
        content_paned.pack(fill=tk.BOTH, expand=True)

        # Tree pane (collapsible, on the left)
        self.tree_pane = ttk.Frame(content_paned, width=250)
        content_paned.add(self.tree_pane, minsize=0, stretch="never")

        # Tree header
        tree_header = ttk.Frame(self.tree_pane)
        tree_header.pack(fill=tk.X)

        ttk.Label(tree_header, text="Optimization History").pack(side=tk.LEFT)

        # Tree view
        tree_container = ttk.Frame(self.tree_pane)
        tree_container.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        self.tree_view = ttk.Treeview(tree_container, show='tree')
        tree_scrollbar = ttk.Scrollbar(tree_container, orient=tk.VERTICAL,
                                       command=self.tree_view.yview)
        self.tree_view.configure(yscrollcommand=tree_scrollbar.set)

        self.tree_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree_view.bind('<<TreeviewSelect>>', self.on_tree_node_selected)

        # Generate script button
        ttk.Button(self.tree_pane, text="Generate Python Script",
                   command=self.generate_script).pack(fill=tk.X, pady=(5, 0))

        # Middle panel: Graph canvas (inside a container for PanedWindow)
        middle_container = ttk.Frame(content_paned)
        content_paned.add(middle_container, minsize=400, stretch="always")

        middle_frame = ttk.Frame(middle_container)
        middle_frame.pack(fill=tk.BOTH, expand=True)

        # Canvas header with toggle buttons
        canvas_header = ttk.Frame(middle_frame)
        canvas_header.pack(fill=tk.X, anchor=tk.W)

        # Toggle button for tree pane (always visible)
        self.toggle_tree_btn = ttk.Button(canvas_header, text="◀", width=3,
                                          command=self.toggle_tree_pane)
        self.toggle_tree_btn.pack(side=tk.LEFT, padx=(0, 5))

        canvas_label = ttk.Label(canvas_header, text="ResourceGraph Visualization")
        canvas_label.pack(side=tk.LEFT)

        # Toggle button for right pane (always visible)
        self.toggle_right_btn = ttk.Button(canvas_header, text="▶", width=3,
                                           command=self.toggle_right_pane)
        self.toggle_right_btn.pack(side=tk.RIGHT, padx=(5, 0))

        # Canvas with scrollbars
        canvas_frame = ttk.Frame(middle_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg='white', width=800, height=600)
        h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)

        self.canvas.configure(xscrollcommand=h_scrollbar.set, yscrollcommand=v_scrollbar.set)
        self.canvas.configure(scrollregion=(0, 0, 1000, 1000))

        # Pack scrollbars BEFORE canvas so they get their full width/height
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bind canvas events
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Control-Button-1>", self.on_canvas_ctrl_click)

        # Mouse wheel scrolling (vertical and horizontal)
        self.canvas.bind("<MouseWheel>", self.on_canvas_mousewheel)  # Windows/Mac vertical
        self.canvas.bind("<Button-4>", self.on_canvas_mousewheel)    # Linux scroll up
        self.canvas.bind("<Button-5>", self.on_canvas_mousewheel)    # Linux scroll down

        # Horizontal scrolling - multiple methods for different platforms
        self.canvas.bind("<Shift-MouseWheel>", self.on_canvas_shift_mousewheel)  # Shift+scroll
        self.canvas.bind("<Shift-Button-4>", self.on_canvas_shift_mousewheel)    # Linux
        self.canvas.bind("<Shift-Button-5>", self.on_canvas_shift_mousewheel)    # Linux
        try:
            self.canvas.bind("<Option-MouseWheel>", self.on_canvas_shift_mousewheel)  # Mac Option+scroll
        except tk.TclError:
            pass  # Not supported on this platform

        # Native horizontal trackpad scrolling (platform-specific, Linux X11 only)
        try:
            self.canvas.bind("<Button-6>", self.on_canvas_horizontal_scroll)  # Linux left
            self.canvas.bind("<Button-7>", self.on_canvas_horizontal_scroll)  # Linux right
        except tk.TclError:
            pass  # Button-6/7 not supported on this platform

        # Right panel: Controls and properties
        self.right_pane = ttk.Frame(content_paned, width=140)
        content_paned.add(self.right_pane, minsize=0, stretch="never")

        # Store reference to content_paned for toggle functionality
        self.content_paned = content_paned

        right_frame = ttk.Frame(self.right_pane)
        right_frame.pack(fill=tk.BOTH, expand=True)

        # Graph info
        info_frame = ttk.LabelFrame(right_frame, text="Graph Information")
        info_frame.pack(fill=tk.X, pady=(0, 5))

        self.graph_info_text = tk.Text(info_frame, height=4, wrap=tk.WORD)
        self.graph_info_text.pack(fill=tk.X, padx=5, pady=5)

        # Selection info
        selection_frame = ttk.LabelFrame(right_frame, text="Selection Properties")
        selection_frame.pack(fill=tk.X, pady=(0, 5))

        self.selection_text = tk.Text(selection_frame, height=8, wrap=tk.WORD)
        selection_scrollbar = ttk.Scrollbar(selection_frame, command=self.selection_text.yview)
        self.selection_text.configure(yscrollcommand=selection_scrollbar.set)

        self.selection_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        selection_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

        # Optimization controls
        opt_frame = ttk.LabelFrame(right_frame, text="Optimization Strategies")
        opt_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # Strategy selection
        ttk.Label(opt_frame, text="Strategy:").pack(anchor=tk.W, padx=5, pady=(5, 0))
        self.strategy_var = tk.StringVar()
        self.strategy_combo = ttk.Combobox(opt_frame, textvariable=self.strategy_var, state="readonly")
        self.strategy_combo['values'] = [s.name for s in self.optimization_strategies]
        self.strategy_combo.pack(fill=tk.X, padx=5, pady=(0, 5))
        self.strategy_combo.bind('<<ComboboxSelected>>', self.on_strategy_selected)

        # Strategy description
        self.strategy_desc_text = tk.Text(opt_frame, height=3, wrap=tk.WORD, state=tk.DISABLED)
        self.strategy_desc_text.pack(fill=tk.X, padx=5, pady=(0, 5))

        # Parameters frame
        self.params_frame = ttk.Frame(opt_frame)
        self.params_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        # Apply button
        self.apply_button = ttk.Button(opt_frame, text="Apply Optimization",
                                     command=self.apply_optimization, state=tk.DISABLED)
        self.apply_button.pack(fill=tk.X, padx=5, pady=5)

        # Placeholder frame for pipeline optimization controls (can be populated later)
        self.pipeline_opt_frame = ttk.Frame(right_frame)
        self.pipeline_opt_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # Status bar at bottom of entire window
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(status_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, padx=2, pady=2)

        # Update initial state
        self.update_graph_info()

        # Set initial sash positions after window is realized
        # This ensures the right panel starts narrower (140px instead of expanding to content)
        self.root.after(100, self._set_initial_sash_positions)

    def _set_initial_sash_positions(self):
        """Set initial sash positions for the PanedWindow."""
        try:
            # Window is 1200px wide, we want:
            # - Left tree pane: ~250px
            # - Middle canvas: flexible (most of the space)
            # - Right pane: ~140px
            window_width = self.root.winfo_width()
            if window_width > 1:  # Window has been realized
                # Position sash between middle and right pane
                # sash_place(index, x, y) - index 1 is between pane 1 and 2
                right_pane_width = 140
                self.content_paned.sash_place(1, window_width - right_pane_width, 0)
        except Exception:
            pass  # Sash positioning failed, use defaults

    def toggle_tree_pane(self):
        """Toggle the visibility of the tree pane."""
        if self.tree_visible:
            # Hide the tree pane by removing it from PanedWindow
            self.content_paned.remove(self.tree_pane)
            self.toggle_tree_btn.configure(text="▶")
            self.tree_visible = False
        else:
            # Show the tree pane by adding it back to PanedWindow at the beginning
            # Get the first pane (middle_container) to insert before it
            panes = self.content_paned.panes()
            if panes:
                self.content_paned.add(self.tree_pane, before=panes[0], minsize=0, stretch="never")
            else:
                self.content_paned.add(self.tree_pane, minsize=0, stretch="never")
            self.toggle_tree_btn.configure(text="◀")
            self.tree_visible = True

    def toggle_right_pane(self):
        """Toggle the visibility of the right pane."""
        if self.right_visible:
            # Hide the right pane by removing it from PanedWindow
            self.content_paned.remove(self.right_pane)
            self.toggle_right_btn.configure(text="◀")
            self.right_visible = False
        else:
            # Show the right pane by adding it back to PanedWindow at the end
            self.content_paned.add(self.right_pane, minsize=0, stretch="never")
            self.toggle_right_btn.configure(text="▶")
            self.right_visible = True

    def on_tree_node_selected(self, event):
        """Handle tree node selection - switch to the selected graph state."""
        selection = self.tree_view.selection()
        if not selection:
            return

        tree_item_id = selection[0]

        # Find the corresponding tree node
        tree_node = self._find_tree_node_by_id(tree_item_id, self.tree_root)
        if tree_node:
            self.current_tree_node = tree_node
            self.current_graph = tree_node.graph
            self.graph_layout = self._create_initial_layout(tree_node.graph)
            self.clear_selection()
            self.update_display(preserve_scroll=False)  # Auto-center when switching graphs
            self.update_graph_info()

    def _find_tree_node_by_id(self, tree_item_id: str, node: OptimizationTreeNode) -> Optional[OptimizationTreeNode]:
        """Recursively find a tree node by its treeview item ID."""
        if node is None:
            return None
        if node.tree_item_id == tree_item_id:
            return node
        for child in node.children:
            result = self._find_tree_node_by_id(tree_item_id, child)
            if result:
                return result
        return None

    def add_tree_node(self, graph: ResourceGraph, label: str, optimization_name: str = None,
                      optimization_params: Dict[str, Any] = None) -> OptimizationTreeNode:
        """Add a new node to the optimization tree."""
        new_node = OptimizationTreeNode(
            graph=graph,
            label=label,
            optimization_name=optimization_name,
            optimization_params=optimization_params
        )

        if self.tree_root is None:
            # This is the first node (root)
            self.tree_root = new_node
            self.current_tree_node = new_node
            # Add to treeview
            tree_item_id = self.tree_view.insert('', 'end', text=label)
            new_node.tree_item_id = tree_item_id
        else:
            # Add as child of current node
            self.current_tree_node.add_child(new_node)
            # Add to treeview
            parent_id = self.current_tree_node.tree_item_id
            tree_item_id = self.tree_view.insert(parent_id, 'end', text=label)
            new_node.tree_item_id = tree_item_id
            # Expand the parent
            self.tree_view.item(parent_id, open=True)

        # Select the new node
        self.tree_view.selection_set(tree_item_id)
        self.tree_view.see(tree_item_id)

        return new_node

    def generate_script(self):
        """Generate a Python script that reproduces the optimization path to the current node."""
        if self.current_tree_node is None:
            messagebox.showinfo("Info", "No optimization tree available")
            return

        # Get path from root to current node
        path = self.current_tree_node.get_path_from_root()

        # Build the script
        script_lines = []
        script_lines.append("#!/usr/bin/env python3")
        script_lines.append("from resource_graph import ResourceGraph")
        script_lines.append("from isa_parser import parse_isa_file")
        script_lines.append("")

        # Root node - file loading
        root_node = path[0]
        if root_node.optimization_params and 'isa_files' in root_node.optimization_params:
            files = root_node.optimization_params['isa_files']
            if isinstance(files, list):
                script_lines.append(f"# Load ISA files")
                script_lines.append(f"isa_files = {repr(files)}")
                script_lines.append("graphs = [parse_isa_file(f) for f in isa_files]")
                if len(files) > 1:
                    script_lines.append("from graph_merger import merge_instructions")
                    script_lines.append("graph = merge_instructions(graphs)")
                else:
                    script_lines.append("graph = graphs[0]")
                script_lines.append("graph.infer_uarch_time()")
                script_lines.append("")

        # Collect all needed imports first
        import_lines = []
        for node in path[1:]:
            if node.optimization_name:
                import_line = self._get_import_for_optimization(node.optimization_name)
                if import_line:
                    for line in import_line.split('\n'):
                        if line and line not in import_lines:
                            import_lines.append(line)

        # Add imports after the initial imports
        if import_lines:
            for import_line in import_lines:
                script_lines.insert(3, import_line)
            script_lines.insert(3 + len(import_lines), "")

        # Apply each optimization in sequence
        for i, node in enumerate(path[1:], 1):
            if node.optimization_name and node.optimization_params:
                script_lines.append(f"# Step {i}: {node.optimization_name}")
                opt_code = self._generate_optimization_code(node.optimization_name, node.optimization_params)
                if opt_code:
                    script_lines.append(opt_code)
                    script_lines.append("")
                else:
                    script_lines.append(f"# TODO: Implement {node.optimization_name} optimization")
                    script_lines.append(f"# Parameters: {node.optimization_params}")
                    script_lines.append("")

        script_lines.append("# Save result")
        script_lines.append("graph.save('optimized_graph.json')")
        script_lines.append("print('Optimization complete!')")

        script = "\n".join(script_lines)

        # Show in a dialog
        self._show_script_dialog(script)

    def _generate_optimization_code(self, opt_name: str, params: Dict[str, Any]) -> Optional[str]:
        """Generate the Python code for a specific optimization."""
        # Simple function call optimizations
        if opt_name == "ALU Integration":
            spec = params.get('alu_spec_file', '')
            nodes = params.get('selected_nodes', [])
            return f"apply_alu_integration(graph, parse_alu_spec_file({spec!r})[0], {nodes!r})"

        elif opt_name == "Memory Port Sharing":
            return f"apply_register_file_sharing(graph, read_ports={params.get('read_ports', 1)}, write_ports={params.get('write_ports', 1)}, read_write_ports={params.get('read_write_ports', 0)})"

        elif opt_name == "Branch Prediction (Not-Taken)":
            pc_node = params.get('pc_node', 'None')
            pc_mux = params.get('pc_mux', 'None')
            not_taken = params.get('not_taken_input', 'None')
            taken = params.get('taken_input', 'None')
            return f"apply_branch_prediction_not_taken(graph, pc_node_id={repr(pc_node)}, pc_mux_id={repr(pc_mux)}, not_taken_input_id={repr(not_taken)}, taken_input_id={repr(taken)})"

        elif opt_name == "Architectural Retiming":
            target = params.get('target_node')
            strategy = params.get('strategy', 'precomputation')
            depth = params.get('depth', 1)
            return f"apply_architectural_retiming(graph, target_node_id={repr(target)}, strategy={repr(strategy)}, depth={depth})"

        elif opt_name == "Change Operation Latency":
            latency_type = params.get('latency_type', 'fixed')
            latency_value = params.get('latency_value', 1)
            nodes = params.get('selected_nodes', [])
            if nodes:
                target = nodes[0]
            else:
                target = None
            if latency_type == 'variable':
                return f"set_operation_variable_latency(graph, {repr(target)}, enable=True)"
            else:
                return f"change_operation_latency(graph, {repr(target)}, {latency_value})"

        elif opt_name == "Retiming":
            direction = params.get('direction', 'later')
            nodes = params.get('selected_nodes', [])
            if direction == 'later':
                return f"apply_retiming_forward(graph, {repr(nodes)})"
            else:
                return f"apply_retiming_backward(graph, {repr(nodes)})"

        elif opt_name == "Register Renaming":
            nodes = params.get('selected_nodes', [])
            num_phys = params.get('num_physical_regs', 64)
            separate = params.get('separate_regfiles', False)
            if nodes:
                resource = nodes[0]
                spec_code = f"RegisterRenamingSpec(resource_name={repr(resource)}, num_physical_regs={num_phys}, separate_regfiles={separate})"
                return f"apply_register_renaming(graph, {spec_code})"
            return None

        elif opt_name == "Resource Sharing/Duplication":
            mode = params.get('mode', 'share')
            nodes = params.get('selected_nodes', [])
            sharing_type = params.get('sharing_type', 'spatial')
            if mode == 'share':
                mode_str = "SharingMode.TEMPORAL" if sharing_type == 'temporal' else "SharingMode.SPATIAL"
                return f"apply_operation_sharing(graph, selected_node_ids={repr(nodes)}, mode={mode_str})"
            else:
                return f"unroll_shared_operations(graph)"

        elif opt_name == "Operation Serialization/Parallelization":
            mode = params.get('mode', 'serialize')
            granularity = params.get('granularity_bits', 8)
            nodes = params.get('selected_nodes', [])
            if mode == 'serialize' and nodes:
                target = nodes[0]
                return f"spec = SerializationSpec({repr(target)}, {granularity})\napply_operation_serialization(graph, [spec])"
            elif mode == 'parallelize':
                return f"# Parallelization requires identifying the serialized operation\n# parallelize_serialized_operations(graph, operation_id='op_id', target_granularity={granularity})"
            return None

        elif opt_name == "Instruction Merging":
            files = params.get('instruction_files', [])
            if files:
                # Build instruction dict
                file_pairs = ', '.join([f"{repr(f)}: {repr(f)}" for f in files])
                return f"# Note: Adjust instruction names as needed\ninstruction_dict = {{{file_pairs}}}\ngraph = merge_instructions(instruction_dict)\ngraph.infer_uarch_time()"
            return None

        elif opt_name == "Manual Pipelining":
            edges = params.get('selected_edges', [])
            stage_name = params.get('stage_name', 'pipeline_stage')
            if edges:
                return f"# Manual pipelining - insert pipeline registers on edges: {edges}\n# This requires custom graph manipulation - see GUI implementation\n# Edges: {edges}, Stage: {stage_name}"
            return None

        elif opt_name == "Multi-Stage Manual Pipelining":
            return f"# Multi-stage pipelining applied via GUI wizard\n# See parameters for details: {params}"

        # Default: return None for unknown optimizations
        return None

    def _format_params_for_script(self, params: Dict[str, Any]) -> str:
        """Format parameters for inclusion in Python script."""
        formatted_params = []
        for key, value in params.items():
            if key == 'isa_files':
                continue  # Already handled
            if isinstance(value, str):
                formatted_params.append(f"{key}={repr(value)}")
            elif isinstance(value, (int, float, bool)):
                formatted_params.append(f"{key}={value}")
            elif isinstance(value, list):
                formatted_params.append(f"{key}={repr(value)}")
            else:
                formatted_params.append(f"{key}={repr(value)}")
        return ", ".join(formatted_params)

    def _get_import_for_optimization(self, opt_name: str) -> Optional[str]:
        """Get the import statement for an optimization."""
        import_map = {
            # Note: Manual Pipelining uses complex GUI wrapper - see generated comments
            "ALU Integration": "from opt.alu_integration import apply_alu_integration\nfrom core.alu_spec_parser import parse_alu_spec_file",
            "Instruction Merging": "from graph_merger import merge_instructions",
            "Parallel Instruction Merging": "from opt.pipeline.parallel_instruction_merging import merge_parallel_instructions",
            "Resource Sharing/Duplication": "from opt.sharing.operation_sharing import apply_operation_sharing, SharingMode\nfrom opt.sharing.unroll_shared_operations import unroll_shared_operations",
            "Memory Port Sharing": "from opt.memory.memory_sharing import apply_register_file_sharing",
            "Operation Serialization/Parallelization": "from operation_serialization import apply_operation_serialization, SerializationSpec\nfrom operation_parallelization import parallelize_serialized_operations",
            "Branch Prediction (Not-Taken)": "from opt.fetch.branch_prediction_not_taken import apply_branch_prediction_not_taken",
            "Retiming": "from retiming_optimization import apply_retiming_forward, apply_retiming_backward",
            "Register Renaming": "from opt.ooo.register_renaming_optimization import apply_register_renaming, RegisterRenamingSpec",
            "Architectural Retiming": "from architectural_retiming import apply_architectural_retiming",
            "Change Operation Latency": "from multi_cycle_operations import change_operation_latency, set_operation_variable_latency",
        }
        return import_map.get(opt_name)

    def _get_function_for_optimization(self, opt_name: str) -> Optional[str]:
        """Get the function name for an optimization."""
        # Returns None if the optimization needs custom script generation
        func_map = {
            "ALU Integration": "apply_alu_integration",
            "Memory Port Sharing": "apply_register_file_sharing",
            "Branch Prediction (Not-Taken)": "apply_branch_prediction_not_taken",
            "Architectural Retiming": "apply_architectural_retiming",
        }
        return func_map.get(opt_name)

    def _show_script_dialog(self, script: str):
        """Show the generated script in a dialog window."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Generated Python Script")
        dialog.geometry("800x600")

        # Text widget with scrollbar
        text_frame = ttk.Frame(dialog)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        text_widget = tk.Text(text_frame, wrap=tk.NONE)
        text_scrollbar_y = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_scrollbar_x = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=text_widget.xview)
        text_widget.configure(yscrollcommand=text_scrollbar_y.set, xscrollcommand=text_scrollbar_x.set)

        text_widget.insert('1.0', script)
        text_widget.configure(state=tk.DISABLED)

        text_widget.grid(row=0, column=0, sticky='nsew')
        text_scrollbar_y.grid(row=0, column=1, sticky='ns')
        text_scrollbar_x.grid(row=1, column=0, sticky='ew')

        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        def copy_to_clipboard():
            self.root.clipboard_clear()
            self.root.clipboard_append(script)
            messagebox.showinfo("Success", "Script copied to clipboard!")

        def save_to_file():
            filename = filedialog.asksaveasfilename(
                defaultextension=".py",
                filetypes=[("Python files", "*.py"), ("All files", "*.*")]
            )
            if filename:
                with open(filename, 'w') as f:
                    f.write(script)
                messagebox.showinfo("Success", f"Script saved to {filename}")

        ttk.Button(button_frame, text="Copy to Clipboard", command=copy_to_clipboard).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save to File", command=save_to_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)

    def _create_optimization_strategies(self) -> List[OptimizationStrategy]:
        """Create the list of available optimization strategies."""

        strategies = []

        # Pipelining optimization
        strategies.append(OptimizationStrategy(
            name="Manual Pipelining",
            description="Add a single pipeline stage at selected edges. Click edges to select them (they turn purple with arrows and labels showing direction). Select edges where you want to insert pipeline registers, then apply this optimization repeatedly to build up your pipeline.",
            apply_function=self._apply_manual_pipelining,
            parameters=[
                {'name': 'selected_edges', 'type': 'selected_edges', 'default': []},
                {'name': 'stage_name', 'type': 'str', 'default': 'pipeline_stage'}
            ]
        ))

        # Multi-stage pipelining
        strategies.append(OptimizationStrategy(
            name="Multi-Stage Manual Pipelining",
            description="Build multi-stage pipelines step-by-step. Set the number of stages, name each stage, then select edges for each stage one at a time. Each stage insertion adds pipeline registers with automatic hazard detection.",
            apply_function=self._apply_multi_stage_pipelining,
            parameters=[
                {'name': 'num_stages', 'type': 'int', 'default': 2, 'min': 1, 'max': 10},
                {'name': 'stage_names', 'type': 'str', 'default': 'fetch,decode'}
            ]
        ))

        # Change operation latency
        strategies.append(OptimizationStrategy(
            name="Change Operation Latency",
            description="Change the latency of an operation. Select an operation node and choose: Fixed (specify cycles 0-16) or Variable (unknown completion time, for caches/I/O). Note: latency_value is only used when type=Fixed. Automatically handles transitions between modes with proper cleanup.",
            apply_function=self._change_operation_latency,
            parameters=[
                {'name': 'selected_nodes', 'type': 'selected_nodes', 'default': []},
                {'name': 'latency_type', 'type': 'choice', 'choices': ['fixed', 'variable'], 'default': 'fixed'},
                {'name': 'latency_value', 'type': 'int', 'default': 1, 'min': 0, 'max': 16}
            ]
        ))

        # ALU integration
        strategies.append(OptimizationStrategy(
            name="ALU Integration",
            description="Integrate selected operation nodes into a shared ALU module. Select the nodes you want to share in the graph, then choose an ALU spec file (.spec) that defines the ALU's operations and opcodes.",
            apply_function=self._apply_alu_integration,
            parameters=[
                {'name': 'selected_nodes', 'type': 'selected_nodes', 'default': []},
                {'name': 'alu_spec_file', 'type': 'file', 'default': ''},
            ]
        ))

        # Graph merging (for multiple ISA files)
        strategies.append(OptimizationStrategy(
            name="Instruction Merging",
            description="Merge multiple instruction ISA files with decode logic.",
            apply_function=self._apply_instruction_merging,
            parameters=[
                {'name': 'instruction_files', 'type': 'file_list', 'default': []}
            ]
        ))

        # Resource sharing/duplication
        strategies.append(OptimizationStrategy(
            name="Resource Sharing/Duplication",
            description="Share or duplicate hardware resources. SHARE: Multiplex operations to save area (spatial = mux-based single cycle, temporal = counter-based multi-cycle). DUPLICATE: Unroll shared operations into parallel hardware for lower latency. Select 2+ nodes of the same type to share/duplicate them.",
            apply_function=self._apply_resource_sharing_or_duplication,
            parameters=[
                {'name': 'selected_nodes', 'type': 'selected_nodes', 'default': []},
                {'name': 'mode', 'type': 'choice', 'choices': ['share', 'duplicate'], 'default': 'share'},
                {'name': 'sharing_type', 'type': 'choice', 'choices': ['spatial', 'temporal'], 'default': 'spatial'}
            ]
        ))

        # Memory sharing
        strategies.append(OptimizationStrategy(
            name="Memory Port Sharing",
            description="Optimize memory access with configurable port types: dedicated read, dedicated write, and dual read-write ports.",
            apply_function=self._apply_register_file_sharing,
            parameters=[
                {'name': 'read_ports', 'type': 'int', 'default': 1, 'min': 0, 'max': 8},
                {'name': 'write_ports', 'type': 'int', 'default': 1, 'min': 0, 'max': 8},
                {'name': 'read_write_ports', 'type': 'int', 'default': 0, 'min': 0, 'max': 8}
            ]
        ))

        # Memory externalization
        strategies.append(OptimizationStrategy(
            name="Memory Externalization",
            description="Convert internal memory to external memory ports. Creates top-level input/output ports for memory interface (read_addr, read_data, write_addr, write_data, write_enable). If byte enable signals exist in the ISA spec, also creates write_be port. Useful for connecting to external memory controllers, caches, or memory-mapped I/O. Select a memory node (dmem, imem, rf, etc.) to externalize.",
            apply_function=self._apply_memory_externalization,
            parameters=[
                {'name': 'selected_nodes', 'type': 'selected_nodes', 'default': []},
                {'name': 'create_read_port', 'type': 'bool', 'default': True},
                {'name': 'create_write_port', 'type': 'bool', 'default': True}
            ]
        ))

        # Operation serialization/parallelization
        strategies.append(OptimizationStrategy(
            name="Operation Serialization/Parallelization",
            description="SERIALIZE: Convert wide operations into narrower operations over multiple cycles to save area. Select an operation node and specify granularity. PARALLELIZE: Convert a serialized operation back into wide parallel form for lower latency. Select any node from the serialization infrastructure (counter, narrow operation, bit slice, etc.).",
            apply_function=self._apply_operation_serialization_or_parallelization,
            parameters=[
                {'name': 'selected_nodes', 'type': 'selected_nodes', 'default': []},
                {'name': 'mode', 'type': 'choice', 'choices': ['serialize', 'parallelize'], 'default': 'serialize'},
                {'name': 'granularity_bits', 'type': 'int', 'default': 8, 'min': 1, 'max': 64}
            ]
        ))

        # Branch prediction (not-taken)
        strategies.append(OptimizationStrategy(
            name="Branch Prediction (Not-Taken)",
            description="Add static not-taken branch prediction with pipeline flush on misprediction. Select nodes in order: (1) PC write node, (2) PC mux/ternary, (3) not-taken input (e.g., PC+4), (4) taken input (e.g., branch target). Leave unselected to auto-detect.",
            apply_function=self._apply_branch_prediction_not_taken,
            parameters=[
                {'name': 'pc_node', 'type': 'selected_node', 'default': None, 'description': 'PC write node (e.g., pc_wr)'},
                {'name': 'pc_mux', 'type': 'selected_node', 'default': None, 'description': 'PC assignment mux or ternary'},
                {'name': 'not_taken_input', 'type': 'selected_node', 'default': None, 'description': 'Not-taken PC input (e.g., pc+4)'},
                {'name': 'taken_input', 'type': 'selected_node', 'default': None, 'description': 'Taken PC input (branch target)'}
            ]
        ))

        # Microarchitectural retiming
        strategies.append(OptimizationStrategy(
            name="Retiming",
            description="Move selected uarch_state registers earlier or later in the pipeline by one cycle. Select one or more uarch_state registers (gray nodes) and choose the direction to move them. This respects retiming rules and properly handles combinational logic.",
            apply_function=self._apply_retiming,
            parameters=[
                {'name': 'selected_nodes', 'type': 'selected_nodes', 'default': []},
                {'name': 'direction', 'type': 'choice', 'choices': ['earlier', 'later'], 'default': 'later'}
            ]
        ))

        # Register Renaming
        strategies.append(OptimizationStrategy(
            name="Register Renaming",
            description="Eliminate false dependencies (WAW/WAR hazards) by mapping architectural registers to a larger pool of physical registers.\n\n"
                       "Select the architectural state resource to rename (e.g., 'rf' node). "
                       "Optionally select specific index nodes (e.g., 'rs', 'rt', 'rd') to rename only those - if none selected, all indices are renamed.\n\n"
                       "Two modes:\n"
                       "• Index Renaming (separate_regfiles=False): Renames indices only, same storage\n"
                       "• Separate Regfiles (separate_regfiles=True): Creates separate Physical RF (PRF) for execution\n"
                       "  - All reads come from PRF using physical indices\n"
                       "  - All writes go to BOTH PRF (physical index) and ARF (architectural index)\n"
                       "  - More realistic hardware model\n\n"
                       "The optimization creates:\n"
                       "- Renamer: Maps architectural → physical register indices\n"
                       "- Denamer: Maps physical → architectural for writes\n"
                       "- Rename table: Tracks current mappings\n"
                       "- Free list: Manages available physical registers\n"
                       "- Physical RF (if separate_regfiles=True): Duplicate register file\n\n"
                       "Benefits:\n"
                       "- Eliminates false WAW (Write-After-Write) hazards\n"
                       "- Eliminates false WAR (Write-After-Read) hazards\n"
                       "- Enables better pipelining and out-of-order execution\n"
                       "- Dependency analysis uses physical register indices",
            apply_function=self._apply_register_renaming,
            parameters=[
                {'name': 'selected_nodes', 'type': 'selected_nodes', 'default': [], 'description': 'Select resource node (e.g., rf) + optional index nodes'},
                {'name': 'num_physical_regs', 'type': 'int', 'default': 64, 'min': 8, 'max': 256, 'description': 'Number of physical registers'},
                {'name': 'separate_regfiles', 'type': 'bool', 'default': False, 'description': 'Create separate Physical RF (True) or just rename indices (False)'}
            ]
        ))

        # Architectural retiming
        strategies.append(OptimizationStrategy(
            name="Architectural Retiming",
            description="Optimize critical paths using 'negative registers' via precomputation or prediction. Select a target node (critical signal), choose strategy (precomputation duplicates logic to run earlier, prediction uses last-value prediction with correction), and set depth (how many cycles early). Depth is limited by the target node's current uarch_time. This technique generalizes optimizations like branch prediction and bypassing.",
            apply_function=self._apply_architectural_retiming,
            parameters=[
                {'name': 'target_node', 'type': 'selected_node', 'default': None, 'description': 'Critical signal to optimize'},
                {'name': 'strategy', 'type': 'choice', 'choices': ['precomputation', 'prediction'], 'default': 'precomputation'},
                {'name': 'depth', 'type': 'int', 'default': 1, 'min': 1, 'description': 'Cycles to move earlier (max = target node uarch_time)'}
            ]
        ))

        # Memory Access Transformation
        strategies.append(OptimizationStrategy(
            name="Memory Access Transformation",
            description="Transform memory accesses to match memory width constraints using bidirectional transformations.\n\n"
                       "First, set the target memory width. Then choose a transformation strategy:\n\n"
                       "1. SET PORT WIDTH (Single-cycle byte selection, recommended):\n"
                       "   - Sets port_width on memory node (e.g., 32 for word-addressed)\n"
                       "   - Transforms accesses to use word address (addr[31:2])\n"
                       "   - Generates byte-selection mux for sub-word accesses (8/16-bit)\n"
                       "   - Leaves full-word accesses unchanged\n"
                       "   - Single cycle, no counter, no multiple ports\n\n"
                       "2. SERIALIZE/PARALLELIZE (Multi-cycle with counter):\n"
                       "   - Forward (narrowing, e.g., 32→16 bits): Adds counter, spreads access across multiple cycles\n"
                       "   - Reverse (widening, e.g., 16→32 bits): Removes counter, restores parallel access\n"
                       "   - Update (re-narrowing, e.g., 16→8 bits): Updates counter width for new granularity\n\n"
                       "3. SPLIT/MERGE (Parallel multi-port):\n"
                       "   - Forward (split): Creates separate memory ports accessed in parallel (NO counter)\n"
                       "   - Reverse (merge): Combines ports back into single wide port\n\n"
                       "4. NO TRANSFORMATION:\n"
                       "   - Just sets the width constraint without transforming the graph\n\n"
                       "Alignment options:\n"
                       "- aligned: Accesses are aligned to port_width (default, simpler hardware)\n"
                       "- unaligned: Support cross-word boundary accesses (e.g., RISC-V C extension)\n\n"
                       "Direction is auto-detected by comparing current access width vs target memory width.\n"
                       "For merge operations, you can optionally select specific ports to merge (otherwise auto-detected).",
            apply_function=self._apply_memory_transformation,
            parameters=[
                {'name': 'memory_name', 'type': 'str', 'default': 'umem', 'description': 'Memory to transform (e.g., umem, dmem, imem)'},
                {'name': 'target_width', 'type': 'int', 'default': 32, 'min': 1, 'max': 128, 'description': 'Target memory port width in bits'},
                {'name': 'strategy', 'type': 'choice', 'choices': ['set_port_width', 'serialize_parallelize', 'split_merge', 'none'], 'default': 'set_port_width'},
                {'name': 'endianness', 'type': 'choice', 'choices': ['little', 'big'], 'default': 'little', 'description': 'Endianness for byte selection'},
                {'name': 'alignment', 'type': 'choice', 'choices': ['aligned', 'unaligned'], 'default': 'aligned', 'description': 'Alignment: aligned (port_width) or unaligned (cross-word support)'},
                {'name': 'selected_ports', 'type': 'selected_nodes', 'default': [], 'description': 'Optional: Select ports to merge (for split_merge reverse)'},
                {'name': 'dry_run', 'type': 'bool', 'default': False, 'description': 'Preview transformation without applying'}
            ]
        ))

        # Unpipelining (reverse pipelining)
        strategies.append(OptimizationStrategy(
            name="Unpipelining",
            description="Remove all pipeline components and restore the design to a single-cycle implementation.\n\n"
                       "This optimization reverses pipelining by:\n"
                       "- Removing pipeline registers and reconnecting original edges\n"
                       "- Removing all hazard detection hardware (comparators, stall signals)\n"
                       "- Removing stall controllers\n"
                       "- Re-inferring timing to collapse all stages to cycle 0\n\n"
                       "Use cases:\n"
                       "- Testing single-cycle vs. pipelined performance\n"
                       "- Reverting pipeline optimizations that didn't meet goals\n"
                       "- Simplifying designs for debugging\n"
                       "- Exploring different pipeline configurations\n\n"
                       "Note: Only works on designs that have been pipelined. "
                       "Identifies pipeline components by metadata, node types, and ID patterns.",
            apply_function=self._apply_unpipelining,
            parameters=[]
        ))

        return strategies

    def load_isa_files(self):
        """Load one or more ISA/ILA files. If multiple files selected, merge them."""
        filenames = filedialog.askopenfilenames(
            title="Select ISA/ILA File(s)",
            filetypes=[
                ("ISA/ILA files", "*.isa *.json"),
                ("ISA files", "*.isa"),
                ("ILA JSON files", "*.json"),
                ("All files", "*.*")
            ]
        )

        if not filenames:
            return

        try:
            if len(filenames) == 1:
                # Single file: load directly
                filename = filenames[0]
                if filename.endswith('.json'):
                    # ILA JSON file
                    graph = ResourceGraph.from_ila_json_file(filename)
                    graph.infer_uarch_time()
                    graph.optimize()
                    self.set_graph(graph)
                    # Initialize tree with root node
                    file_label = os.path.basename(filename)
                    self.add_tree_node(graph.copy(), file_label,
                                     optimization_params={'isa_files': list(filenames)})
                    self.status_var.set(f"Loaded ILA JSON file: {file_label}")
                else:
                    # ISA file
                    graph = ResourceGraph.from_isa_file(filename)
                    graph.infer_uarch_time()
                    graph.optimize()
                    self.set_graph(graph)
                    # Initialize tree with root node
                    file_label = os.path.basename(filename)
                    self.add_tree_node(graph.copy(), file_label,
                                     optimization_params={'isa_files': list(filenames)})
                    self.status_var.set(f"Loaded ISA file: {file_label}")
            else:
                # Multiple files: merge them
                instruction_files = {}
                for filename in filenames:
                    # Extract instruction name from filename
                    base_name = os.path.splitext(os.path.basename(filename))[0]
                    if base_name.endswith('_instr'):
                        instr_name = base_name[:-6]  # Remove '_instr'
                    else:
                        instr_name = base_name
                    instruction_files[instr_name] = filename

                graph = merge_instructions(instruction_files)
                graph.infer_uarch_time()
                self.set_graph(graph)
                # Initialize tree with root node
                file_types = set(os.path.splitext(f)[1] for f in filenames)
                file_desc = "ISA/ILA" if len(file_types) > 1 else ("ILA" if ".json" in file_types else "ISA")
                file_label = f"Merged ({len(filenames)} files)"
                self.add_tree_node(graph.copy(), file_label,
                                 optimization_params={'isa_files': list(filenames)})
                self.status_var.set(f"Merged {len(filenames)} {file_desc} files")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file(s): {e}")
            self.status_var.set("Failed to load file(s)")

    def load_verilog_file(self):
        """Load a Verilog/SystemVerilog file."""
        filename = filedialog.askopenfilename(
            title="Select Verilog File",
            filetypes=[
                ("Verilog files", "*.v *.sv"),
                ("Verilog", "*.v"),
                ("SystemVerilog", "*.sv"),
                ("All files", "*.*")
            ]
        )

        if not filename:
            return

        try:
            graph = ResourceGraph.from_verilog_file(filename)
            graph.infer_uarch_time()
            graph.optimize()
            self.set_graph(graph)
            # Initialize tree with root node
            file_label = os.path.basename(filename)
            self.add_tree_node(graph.copy(), file_label,
                             optimization_params={'verilog_file': filename})
            self.status_var.set(f"Loaded Verilog file: {file_label}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load Verilog file: {e}")
            self.status_var.set("Failed to load Verilog file")

    def load_sail_files(self):
        """Load one or more SAIL files. If multiple files selected, merge them."""
        filenames = filedialog.askopenfilenames(
            title="Select SAIL File(s)",
            filetypes=[("SAIL files", "*.sail"), ("All files", "*.*")]
        )

        if not filenames:
            return

        try:
            if len(filenames) == 1:
                # Single file: load directly
                graph = ResourceGraph.from_sail_file(filenames[0])
                graph.infer_uarch_time()
                graph.optimize()
                self.set_graph(graph)
                # Initialize tree with root node
                file_label = os.path.basename(filenames[0])
                self.add_tree_node(graph.copy(), file_label,
                                 optimization_params={'sail_files': list(filenames)})
                self.status_var.set(f"Loaded SAIL file: {file_label}")
            else:
                # Multiple files: merge them
                instruction_files = {}
                for filename in filenames:
                    # Extract instruction name from filename
                    base_name = os.path.splitext(os.path.basename(filename))[0]
                    if base_name.endswith('_instr'):
                        instr_name = base_name[:-6]  # Remove '_instr'
                    else:
                        instr_name = base_name
                    instruction_files[instr_name] = filename

                graph = merge_instructions(instruction_files)
                graph.infer_uarch_time()
                self.set_graph(graph)
                # Initialize tree with root node
                file_label = f"Merged SAIL ({len(filenames)} files)"
                self.add_tree_node(graph.copy(), file_label,
                                 optimization_params={'sail_files': list(filenames)})
                self.status_var.set(f"Merged {len(filenames)} SAIL files")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load SAIL file(s): {e}")
            self.status_var.set("Failed to load SAIL file(s)")

    def save_graph(self):
        """Save the current graph to a file."""
        if not self.current_graph:
            messagebox.showwarning("Warning", "No graph to save")
            return

        filename = filedialog.asksaveasfilename(
            title="Save ResourceGraph",
            defaultextension=".rgraph",
            filetypes=[("ResourceGraph files", "*.rgraph"), ("JSON files", "*.json"), ("All files", "*.*")]
        )

        if not filename:
            return

        try:
            self.current_graph.save_to_file(filename)
            self.status_var.set(f"Saved graph to: {os.path.basename(filename)}")
            messagebox.showinfo("Success", f"Graph saved to {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save graph: {e}")
            self.status_var.set("Failed to save graph")

    def load_graph(self):
        """Load a graph from a file."""
        filename = filedialog.askopenfilename(
            title="Load ResourceGraph",
            filetypes=[("ResourceGraph files", "*.rgraph"), ("JSON files", "*.json"), ("All files", "*.*")]
        )

        if not filename:
            return

        try:
            graph = ResourceGraph.load_from_file(filename)
            self.set_graph(graph)
            self.status_var.set(f"Loaded graph from: {os.path.basename(filename)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load graph: {e}")
            self.status_var.set("Failed to load graph")

    def export_verilog(self):
        """Export the current graph as Verilog RTL."""
        if not self.current_graph:
            messagebox.showwarning("Warning", "No graph to export")
            return

        filename = filedialog.asksaveasfilename(
            title="Export Verilog",
            defaultextension=".v",
            filetypes=[("Verilog files", "*.v"), ("SystemVerilog files", "*.sv"), ("All files", "*.*")]
        )

        if not filename:
            return

        try:
            # Extract module name from filename (without extension)
            module_name = os.path.splitext(os.path.basename(filename))[0]

            # Generate Verilog code
            self.status_var.set("Generating Verilog...")
            self.root.update()  # Update GUI to show status

            verilog_code = generate_verilog(self.current_graph, module_name)

            # Write to file
            with open(filename, 'w') as f:
                f.write(verilog_code)

            self.status_var.set(f"Exported Verilog to: {os.path.basename(filename)}")
            messagebox.showinfo("Success", f"Verilog exported to {filename}")
        except Exception as e:
            error_msg = f"Failed to export Verilog: {e}\n\n{traceback.format_exc()}"
            messagebox.showerror("Error", error_msg)
            self.status_var.set("Failed to export Verilog")

    def set_graph(self, graph: ResourceGraph):
        """Set the current graph and update the display."""
        self.current_graph = graph
        self.graph_layout = self._create_initial_layout(graph)
        self.clear_selection()
        self.update_display(preserve_scroll=False)  # Auto-center for new graph
        self.update_graph_info()

        # Enable optimization controls
        self.apply_button.configure(state=tk.NORMAL)

    def _create_initial_layout(self, graph: ResourceGraph) -> GraphLayout:
        """Create an initial layout for the graph nodes."""
        if not graph.nodes:
            return GraphLayout({}, 800, 600)

        # Use smart layout by default
        positions = self.layout_engine.smart_layout(graph)
        return GraphLayout(positions, 800, 600)

    def on_layout_changed(self, event=None):
        """Handle layout algorithm selection change."""
        if self.current_graph:
            self.apply_layout()

    def on_display_option_changed(self):
        """Handle display option changes."""
        if self.current_graph:
            self.update_display()

    def apply_layout(self):
        """Apply the selected layout algorithm."""
        if not self.current_graph:
            return

        layout_name = self.layout_var.get()

        # Strip complexity indicator from layout name
        layout_base = layout_name.split()[0]

        # Run all layouts in background thread to keep GUI responsive
        self.status_var.set(f"Computing {layout_base} layout...")
        self.root.update_idletasks()

        thread = threading.Thread(target=self._apply_layout_thread, args=(layout_base,))
        thread.daemon = True
        thread.start()

    def _apply_layout_internal(self, layout_name: str, from_thread: bool = False):
        """Internal method to compute layout (can be called from thread)."""
        if layout_name == "Smart":
            positions = self.layout_engine.smart_layout(self.current_graph)
        elif layout_name == "Architectural":
            positions = self.layout_engine.architectural_layout(self.current_graph)
        elif layout_name == "Pipeline":
            positions = self.layout_engine.pipeline_viewer_layout(self.current_graph)
            # Don't apply optimizations for pipeline viewer - preserve the careful layout
            self.graph_layout.node_positions = positions
            if from_thread:
                self.root.after(0, lambda: self.update_display(preserve_scroll=False))
            else:
                self.update_display(preserve_scroll=False)  # Auto-center for new layout
            return
        elif layout_name == "Timeline":
            positions = self.layout_engine.timeline_layout(self.current_graph)
        elif layout_name == "Hierarchical":
            positions = self.layout_engine.hierarchical_layout(self.current_graph)
        elif layout_name == "Force-Directed":
            positions = self.layout_engine.force_directed_layout(self.current_graph)
        elif layout_name == "Circular":
            positions = self.layout_engine.circular_layout(self.current_graph)
        elif layout_name == "Grid":
            positions = self.layout_engine.grid_layout(self.current_graph)
        elif layout_name == "Layered":
            positions = self.layout_engine.layered_layout(self.current_graph)
        else:
            return

        # Apply layout optimization
        positions = self.layout_optimizer.reduce_edge_crossings(self.current_graph, positions)
        positions = self.layout_optimizer.improve_node_distribution(positions, 800, 600)

        self.graph_layout.node_positions = positions

        if from_thread:
            # Schedule display update on main thread
            self.root.after(0, lambda: self.update_display(preserve_scroll=False))
        else:
            self.update_display(preserve_scroll=False)  # Auto-center for new layout

    def _apply_layout_thread(self, layout_name: str):
        """Run layout computation in a separate thread."""
        try:
            self._apply_layout_internal(layout_name, from_thread=True)
            # Update status on main thread
            self.root.after(0, lambda: self.status_var.set("Ready"))
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Layout failed: {e}"))


    def update_display(self, preserve_scroll=True):
        """Update the canvas display with current graph and layout.

        Args:
            preserve_scroll: If True, maintain current scroll position. If False, auto-center.
        """
        if not self.current_graph or not self.graph_layout:
            self.canvas.delete("all")
            return

        # Save current scroll position before clearing
        saved_xview = self.canvas.xview() if preserve_scroll else None
        saved_yview = self.canvas.yview() if preserve_scroll else None

        self.canvas.delete("all")
        self.node_items.clear()
        self.edge_items.clear()
        self.node_labels.clear()

        # Draw edges first (so they appear behind nodes)
        for edge in self.current_graph.edges.values():
            self._draw_edge(edge)

        # Draw nodes
        for node in self.current_graph.nodes.values():
            self._draw_node(node)

        # Update scroll region to fit all nodes with padding
        if self.graph_layout.node_positions:
            min_x = min(pos.x for pos in self.graph_layout.node_positions.values())
            max_x = max(pos.x for pos in self.graph_layout.node_positions.values())
            min_y = min(pos.y for pos in self.graph_layout.node_positions.values())
            max_y = max(pos.y for pos in self.graph_layout.node_positions.values())

            # Add padding around the content (node radius + label space)
            padding = 60
            scroll_x1 = min_x - padding
            scroll_y1 = min_y - padding
            scroll_x2 = max_x + padding
            scroll_y2 = max_y + padding

            self.canvas.configure(scrollregion=(scroll_x1, scroll_y1, scroll_x2, scroll_y2))

            # Restore scroll position or auto-center
            if preserve_scroll and saved_xview and saved_yview:
                # Restore the saved scroll position
                self.canvas.xview_moveto(saved_xview[0])
                self.canvas.yview_moveto(saved_yview[0])
            else:
                # Auto-scroll to show all content (center the view)
                canvas_width = self.canvas.winfo_width()
                canvas_height = self.canvas.winfo_height()
                if canvas_width > 1 and canvas_height > 1:  # Only if canvas is visible
                    content_width = scroll_x2 - scroll_x1
                    content_height = scroll_y2 - scroll_y1

                    # Calculate center of content
                    center_x = (scroll_x1 + scroll_x2) / 2
                    center_y = (scroll_y1 + scroll_y2) / 2

                    # Scroll to center the content
                    if content_width > 0:
                        x_fraction = (center_x - scroll_x1) / content_width
                        self.canvas.xview_moveto(max(0, x_fraction - 0.5))
                    if content_height > 0:
                        y_fraction = (center_y - scroll_y1) / content_height
                        self.canvas.yview_moveto(max(0, y_fraction - 0.5))

    def _draw_gate_shape(self, pos: Point, gate_type: str, color: str) -> List[int]:
        """Draw a logic gate shape and return canvas item IDs."""
        items = []
        size = 25

        # Common gate body (rounded rectangle or special shape)
        if gate_type in ['and', 'nand']:
            # AND gate: D-shaped
            body = self.canvas.create_arc(
                pos.x - size//2, pos.y - size,
                pos.x + size*1.5, pos.y + size,
                start=270, extent=180, style=tk.PIESLICE,
                fill=color, outline="black", width=2
            )
            items.append(body)
            if gate_type == 'nand':
                # Add inverter bubble
                bubble = self.canvas.create_oval(
                    pos.x + size*0.75, pos.y - 4,
                    pos.x + size*0.75 + 8, pos.y + 4,
                    fill="white", outline="black", width=2
                )
                items.append(bubble)
        elif gate_type in ['or', 'nor']:
            # OR gate: curved shape
            body = self.canvas.create_polygon(
                pos.x - size, pos.y - size*0.8,
                pos.x - size*0.5, pos.y - size*0.8,
                pos.x + size, pos.y,
                pos.x - size*0.5, pos.y + size*0.8,
                pos.x - size, pos.y + size*0.8,
                pos.x - size*0.3, pos.y,
                fill=color, outline="black", width=2, smooth=True
            )
            items.append(body)
            if gate_type == 'nor':
                # Add inverter bubble
                bubble = self.canvas.create_oval(
                    pos.x + size, pos.y - 4,
                    pos.x + size + 8, pos.y + 4,
                    fill="white", outline="black", width=2
                )
                items.append(bubble)
        elif gate_type in ['xor', 'xnor']:
            # XOR gate: OR shape with extra arc
            extra_arc = self.canvas.create_arc(
                pos.x - size*1.2, pos.y - size*0.8,
                pos.x - size*0.7, pos.y + size*0.8,
                start=270, extent=180, style=tk.ARC,
                outline="black", width=2
            )
            items.append(extra_arc)
            body = self.canvas.create_polygon(
                pos.x - size, pos.y - size*0.8,
                pos.x - size*0.5, pos.y - size*0.8,
                pos.x + size, pos.y,
                pos.x - size*0.5, pos.y + size*0.8,
                pos.x - size, pos.y + size*0.8,
                pos.x - size*0.3, pos.y,
                fill=color, outline="black", width=2, smooth=True
            )
            items.append(body)
            if gate_type == 'xnor':
                # Add inverter bubble
                bubble = self.canvas.create_oval(
                    pos.x + size, pos.y - 4,
                    pos.x + size + 8, pos.y + 4,
                    fill="white", outline="black", width=2
                )
                items.append(bubble)
        elif gate_type in ['not', 'inv']:
            # NOT gate: triangle with bubble
            body = self.canvas.create_polygon(
                pos.x - size, pos.y - size*0.7,
                pos.x - size, pos.y + size*0.7,
                pos.x + size*0.7, pos.y,
                fill=color, outline="black", width=2
            )
            items.append(body)
            # Inverter bubble
            bubble = self.canvas.create_oval(
                pos.x + size*0.7, pos.y - 4,
                pos.x + size*0.7 + 8, pos.y + 4,
                fill="white", outline="black", width=2
            )
            items.append(bubble)
        else:
            # Default: circle
            circle = self.canvas.create_oval(
                pos.x - size*0.7, pos.y - size*0.7,
                pos.x + size*0.7, pos.y + size*0.7,
                fill=color, outline="black", width=2
            )
            items.append(circle)

        return items

    def _draw_mux_shape(self, pos: Point, color: str) -> List[int]:
        """Draw a multiplexer as a trapezoid and return canvas item IDs."""
        items = []
        width = 30
        height = 40

        # Trapezoid shape
        body = self.canvas.create_polygon(
            pos.x - width*0.5, pos.y - height*0.5,  # Top left
            pos.x + width*0.5, pos.y - height*0.5,  # Top right
            pos.x + width*0.8, pos.y + height*0.5,  # Bottom right
            pos.x - width*0.8, pos.y + height*0.5,  # Bottom left
            fill=color, outline="black", width=2
        )
        items.append(body)

        # Add "MUX" text
        text = self.canvas.create_text(
            pos.x, pos.y,
            text="MUX", font=("Arial", 8, "bold"),
            anchor=tk.CENTER, fill="black"
        )
        items.append(text)

        return items

    def _draw_register_shape(self, pos: Point, color: str) -> List[int]:
        """Draw a register as a rectangle and return canvas item IDs."""
        items = []
        width = 35
        height = 30

        # Rectangle body
        body = self.canvas.create_rectangle(
            pos.x - width*0.5, pos.y - height*0.5,
            pos.x + width*0.5, pos.y + height*0.5,
            fill=color, outline="black", width=3
        )
        items.append(body)

        # Add clock symbol (small triangle)
        clock = self.canvas.create_polygon(
            pos.x - width*0.4, pos.y + height*0.5,
            pos.x - width*0.2, pos.y + height*0.5,
            pos.x - width*0.3, pos.y + height*0.3,
            fill="black"
        )
        items.append(clock)

        return items

    def _get_operator_type(self, node: Node) -> Optional[str]:
        """Determine the operator type from node data."""
        node_type = node.data.get('type', '').lower()
        display_name = node.data.get('display_name', node.id).lower()
        operation = node.data.get('operation', '').lower()

        # Check for logic operations
        for keyword in ['and', 'nand', 'or', 'nor', 'xor', 'xnor', 'not', 'inv']:
            if keyword in operation or keyword in display_name:
                return keyword

        # Check for mux
        if 'mux' in operation or 'mux' in display_name or 'select' in operation:
            return 'mux'

        # Check for registers
        if 'pipeline' in node_type or node_type == 'uarch_state' or 'register' in display_name:
            return 'register'

        return None

    def _draw_node(self, node: Node):
        """Draw a node on the canvas."""
        pos = self.graph_layout.node_positions.get(node.id)
        if not pos:
            return

        # Node appearance
        radius = 20
        color = "lightblue"

        # Color based on node type
        node_type = node.data.get('type', '')
        if node_type == 'isa_state':
            color = "lightgreen"
        elif node_type == 'instruction_enable':
            color = "orange"
        elif node_type == 'uarch_counter':
            color = "mediumpurple"
        elif 'pipeline' in node_type:
            color = "lightcoral"
        elif node.is_arch_state:
            color = "gold"
        elif node.is_uarch_state:
            color = "lightgray"
        elif node.data.get('shared_resource'):
            color = "lightsalmon"  # Highlight shared resources

        # Highlight selected nodes
        if node.id in self.selected_nodes:
            color = "red"

        # Draw node with symbolic shape if enabled
        items = []
        if self.symbolic_operators_var.get():
            op_type = self._get_operator_type(node)
            if op_type == 'mux':
                items = self._draw_mux_shape(pos, color)
            elif op_type == 'register':
                items = self._draw_register_shape(pos, color)
            elif op_type in ['and', 'nand', 'or', 'nor', 'xor', 'xnor', 'not', 'inv']:
                items = self._draw_gate_shape(pos, op_type, color)

        # Default to circle if no symbolic shape or symbolic mode off
        if not items:
            item_id = self.canvas.create_oval(
                pos.x - radius, pos.y - radius,
                pos.x + radius, pos.y + radius,
                fill=color, outline="black", width=2
            )
            items.append(item_id)

        # Store the primary item for click detection (first item in the list)
        # The click handlers expect a single item ID
        self.node_items[node.id] = items[0]

        # Draw timing information inside node if enabled
        if self.show_timing_var.get() and node.uarch_time is not None:
            timing_id = self.canvas.create_text(
                pos.x, pos.y,
                text=str(node.uarch_time), font=("Arial", 10, "bold"),
                anchor=tk.CENTER, fill="black"
            )
            # Store timing text with a special key
            self.node_labels[f"{node.id}_timing"] = timing_id

        # Draw node label
        display_name = node.data.get('display_name', node.id)
        if len(display_name) > 12:
            display_name = display_name[:10] + "..."

        label_id = self.canvas.create_text(
            pos.x, pos.y + radius + 15,
            text=display_name, font=("Arial", 8), anchor=tk.CENTER,
            fill="black"
        )
        self.node_labels[node.id] = label_id

    def _draw_edge(self, edge: Edge):
        """Draw an edge on the canvas."""
        source_pos = self.graph_layout.node_positions.get(edge.source.id)
        target_pos = self.graph_layout.node_positions.get(edge.target.id)

        if not source_pos or not target_pos:
            return

        # Edge appearance
        color = "black"
        width = 1

        # Color based on edge type
        edge_type = edge.data.get('type', '')
        if edge_type == 'assignment':
            color = "blue"
        elif edge_type == 'array_index':
            color = "green"
        elif 'pipeline' in edge_type:
            color = "purple"
        elif 'hazard' in edge_type:
            color = "red"
            width = 2
        elif edge_type == 'resource_control':
            color = "orange"
            width = 2
        elif edge_type == 'operand':
            color = "darkblue"

        # Highlight selected edges
        if edge.id in self.selected_edges:
            color = "purple"
            width = 4

        # Highlight edges in multistage pipeline selection with different colors per stage
        # If an edge is in multiple cuts, show it with a thicker line and use the lowest cut's color
        if self.multistage_panel_visible:
            stage_colors = ["#FF6B6B", "#4ECDC4", "#DDA0DD", "#FFA07A", "#98D8C8", "#FFB6C1", "#87CEEB", "#45B7D1"]
            cuts_with_edge = []
            for stage_idx, edges in self.multistage_edges_per_stage.items():
                if edge.id in edges:
                    cuts_with_edge.append(stage_idx)

            if cuts_with_edge:
                # Use the first cut's color
                color = stage_colors[cuts_with_edge[0] % len(stage_colors)]
                # Thicker line if in multiple cuts
                width = 3 + len(cuts_with_edge) - 1

        # Draw edge line with prominent arrowhead
        # For long edges, make arrows much bigger to be visible
        arrow_size = max(20, int(width * 8))  # Scale arrow with line width
        item_id = self.canvas.create_line(
            source_pos.x, source_pos.y,
            target_pos.x, target_pos.y,
            fill=color, width=width, arrow=tk.LAST,
            arrowshape=(arrow_size, arrow_size + 8, arrow_size // 2)  # Much larger arrows
        )
        self.edge_items[edge.id] = item_id

        # Fallback: Add a small circle at target to show direction if arrows aren't visible
        if edge.id in self.selected_edges:
            # Draw a small filled circle at the target end
            circle_radius = 8
            circle_id = self.canvas.create_oval(
                target_pos.x - circle_radius, target_pos.y - circle_radius,
                target_pos.x + circle_radius, target_pos.y + circle_radius,
                fill=color, outline="white", width=2
            )
            self.edge_items[f"{edge.id}_target_circle"] = circle_id

        # Add edge label for selected edges to show direction clearly
        if edge.id in self.selected_edges:
            # Calculate label position at midpoint
            mid_x = (source_pos.x + target_pos.x) / 2
            mid_y = (source_pos.y + target_pos.y) / 2

            # Create edge label showing direction
            edge_label = f"{edge.source.id} → {edge.target.id}"
            # Shorten long names for readability
            if len(edge_label) > 30:
                source_name = edge.source.id[:8] + "..." if len(edge.source.id) > 8 else edge.source.id
                target_name = edge.target.id[:8] + "..." if len(edge.target.id) > 8 else edge.target.id
                edge_label = f"{source_name} → {target_name}"

            # Create white background rectangle first
            bbox = self.canvas.bbox("all")  # Get a rough size estimate
            text_width = len(edge_label) * 6  # Rough estimate
            text_height = 12

            bg_id = self.canvas.create_rectangle(
                mid_x - text_width//2 - 2, mid_y - 15 - text_height//2 - 1,
                mid_x + text_width//2 + 2, mid_y - 15 + text_height//2 + 1,
                fill="white", outline="gray", width=1
            )

            label_id = self.canvas.create_text(
                mid_x, mid_y - 15,  # Offset above the edge
                text=edge_label, font=("Arial", 8, "bold"),
                anchor=tk.CENTER, fill="purple"
            )

            # Store both background and text
            self.edge_items[f"{edge.id}_label_bg"] = bg_id
            # Store edge labels with special key
            self.edge_items[f"{edge.id}_label"] = label_id

        # Add label for edges in multiple cuts
        if self.multistage_panel_visible:
            cuts_with_edge = [i for i, edges in self.multistage_edges_per_stage.items() if edge.id in edges]
            if len(cuts_with_edge) > 1:
                # Calculate label position at midpoint
                mid_x = (source_pos.x + target_pos.x) / 2
                mid_y = (source_pos.y + target_pos.y) / 2

                # Show which cuts this edge is in
                cut_label = f"Cuts: {', '.join([str(i+1) for i in cuts_with_edge])}"

                # Create background
                text_width = len(cut_label) * 6
                text_height = 12

                bg_id = self.canvas.create_rectangle(
                    mid_x - text_width//2 - 2, mid_y + 5 - text_height//2 - 1,
                    mid_x + text_width//2 + 2, mid_y + 5 + text_height//2 + 1,
                    fill="yellow", outline="black", width=1
                )

                label_id = self.canvas.create_text(
                    mid_x, mid_y + 5,  # Offset below the edge
                    text=cut_label, font=("Arial", 7, "bold"),
                    anchor=tk.CENTER, fill="black"
                )

                self.edge_items[f"{edge.id}_multi_cut_bg"] = bg_id
                self.edge_items[f"{edge.id}_multi_cut_label"] = label_id

    def on_canvas_click(self, event):
        """Handle canvas click events."""
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        # Find clicked item
        clicked_item = self.canvas.find_closest(x, y)[0]

        # Check if it's a node
        clicked_node = None
        for node_id, item_id in self.node_items.items():
            if item_id == clicked_item:
                clicked_node = node_id
                break

        if clicked_node:
            # If multistage panel is active, don't allow node selection
            if self.multistage_panel_visible:
                self.status_var.set("Click edges (not nodes) to select for pipeline stage")
                return

            # Single selection (clear others first)
            self.clear_selection()
            self.selected_nodes.add(clicked_node)
            self.dragging_node = clicked_node
            self.drag_start_pos = (x, y)
            self.update_display()
            self.update_selection_info()
            self.update_parameter_display()
        else:
            # Check if it's an edge
            clicked_edge = None
            for edge_id, item_id in self.edge_items.items():
                if item_id == clicked_item:
                    clicked_edge = edge_id
                    break

            if clicked_edge:
                # Don't allow selection of state_update edges (conceptual edges for arch state forwarding)
                if clicked_edge in self.current_graph.edges:
                    edge = self.current_graph.edges[clicked_edge]
                    if edge.data and edge.data.get('type') == 'state_update':
                        print(f"Cannot select state_update edge {edge.source.id} -> {edge.target.id} (conceptual forwarding edge)")
                        return

                # If multistage panel is active, add to current stage's edge list
                if self.multistage_panel_visible and hasattr(self, 'multistage_num_cuts'):
                    stage_edges = self.multistage_edges_per_stage[self.multistage_current_stage]
                    if clicked_edge not in stage_edges:
                        stage_edges.append(clicked_edge)
                        self._update_stage_label(self.multistage_current_stage)

                        # Check if this edge is in other stages
                        other_stages = [i for i in range(self.multistage_num_cuts)
                                       if i != self.multistage_current_stage and clicked_edge in self.multistage_edges_per_stage[i]]

                        if other_stages:
                            stage_list = ", ".join([f"Cut {i+1}" for i in other_stages])
                            self.status_var.set(f"Added edge to Cut {self.multistage_current_stage + 1} (also in {stage_list})")
                        else:
                            self.status_var.set(f"Added edge to Cut {self.multistage_current_stage + 1} ({len(stage_edges)} edges)")
                        self.update_display()  # Refresh to show colored edge
                    else:
                        self.status_var.set(f"Edge already in Cut {self.multistage_current_stage + 1}")
                    return

                self.clear_selection()
                self.selected_edges.add(clicked_edge)
                self.update_display()
                self.update_selection_info()
                self.update_parameter_display()
            else:
                # Clicked on empty space
                if not self.multistage_panel_visible:
                    self.clear_selection()

    def on_canvas_ctrl_click(self, event):
        """Handle Ctrl+click for multi-selection."""
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        clicked_item = self.canvas.find_closest(x, y)[0]

        # Check if it's a node
        for node_id, item_id in self.node_items.items():
            if item_id == clicked_item:
                # If multistage panel is active, don't allow node selection
                if self.multistage_panel_visible:
                    self.status_var.set("Click edges (not nodes) to select for pipeline stage")
                    return

                if node_id in self.selected_nodes:
                    self.selected_nodes.remove(node_id)
                else:
                    self.selected_nodes.add(node_id)
                self.update_display()
                self.update_selection_info()
                self.update_parameter_display()
                return

        # Check if it's an edge
        for edge_id, item_id in self.edge_items.items():
            if item_id == clicked_item:
                # Don't allow selection of state_update edges
                if edge_id in self.current_graph.edges:
                    edge = self.current_graph.edges[edge_id]
                    if edge.data and edge.data.get('type') == 'state_update':
                        print(f"Cannot select state_update edge {edge.source.id} -> {edge.target.id} (conceptual forwarding edge)")
                        return

                # If multistage panel is active, toggle edge in/out of current stage
                if self.multistage_panel_visible and hasattr(self, 'multistage_num_cuts'):
                    stage_edges = self.multistage_edges_per_stage[self.multistage_current_stage]
                    if edge_id in stage_edges:
                        stage_edges.remove(edge_id)
                        self._update_stage_label(self.multistage_current_stage)
                        self.status_var.set(f"Removed edge from Cut {self.multistage_current_stage + 1} ({len(stage_edges)} edges)")
                    else:
                        stage_edges.append(edge_id)
                        self._update_stage_label(self.multistage_current_stage)
                        self.status_var.set(f"Added edge to Cut {self.multistage_current_stage + 1} ({len(stage_edges)} edges)")
                    self.update_display()  # Refresh to show colored edge
                    return

                if edge_id in self.selected_edges:
                    self.selected_edges.remove(edge_id)
                else:
                    self.selected_edges.add(edge_id)
                self.update_display()
                self.update_selection_info()
                self.update_parameter_display()
                return

    def on_canvas_drag(self, event):
        """Handle canvas drag events for moving nodes."""
        if self.dragging_node and self.drag_start_pos:
            x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            dx = x - self.drag_start_pos[0]
            dy = y - self.drag_start_pos[1]

            # Update node position
            pos = self.graph_layout.node_positions[self.dragging_node]
            pos.x += dx
            pos.y += dy

            # No bounds checking - let nodes go anywhere
            # Scroll region will expand automatically in update_display()

            self.drag_start_pos = (x, y)
            self.update_display()

    def on_canvas_release(self, event):
        """Handle canvas mouse release."""
        self.dragging_node = None
        self.drag_start_pos = None

    def on_canvas_mousewheel(self, event):
        """Handle vertical mouse wheel scrolling."""
        # Try to detect horizontal scrolling on some platforms
        # On macOS, trackpad horizontal scrolling might set event.state differently
        if hasattr(event, 'state') and (event.state & 0x1):  # Shift key
            # Treat as horizontal scroll
            self.on_canvas_shift_mousewheel(event)
            return

        if event.num == 4 or event.delta > 0:
            # Scroll up (Linux Button-4 or Windows/Mac positive delta)
            # On Windows, delta is typically 120 per notch
            amount = -1 if event.num == 4 else int(-event.delta / 120)
            self.canvas.yview_scroll(amount, "units")
        elif event.num == 5 or event.delta < 0:
            # Scroll down (Linux Button-5 or Windows/Mac negative delta)
            amount = 1 if event.num == 5 else int(-event.delta / 120)
            self.canvas.yview_scroll(amount, "units")

    def on_canvas_shift_mousewheel(self, event):
        """
        Handle horizontal mouse wheel scrolling (with Shift or Option key).

        For Windows trackpad users: Hold Shift and scroll vertically to scroll horizontally.
        """
        if event.num == 4 or event.delta > 0:
            # Scroll left (Linux Button-4 or Windows/Mac positive delta)
            # On Windows, delta is typically 120 per notch
            amount = -1 if event.num == 4 else int(-event.delta / 120)
            self.canvas.xview_scroll(amount, "units")
        elif event.num == 5 or event.delta < 0:
            # Scroll right (Linux Button-5 or Windows/Mac negative delta)
            amount = 1 if event.num == 5 else int(-event.delta / 120)
            self.canvas.xview_scroll(amount, "units")

    def on_canvas_horizontal_scroll(self, event):
        """Handle native horizontal trackpad scrolling (Linux Button-6/7)."""
        if event.num == 6:
            # Scroll left
            self.canvas.xview_scroll(-1, "units")
        elif event.num == 7:
            # Scroll right
            self.canvas.xview_scroll(1, "units")

    def clear_selection(self):
        """Clear all selections."""
        self.selected_nodes.clear()
        self.selected_edges.clear()
        self.update_display()
        self.update_selection_info()

    def cleanup_graph(self):
        """Manually clean up disconnected nodes from the current graph."""
        if not self.current_graph:
            messagebox.showwarning("Warning", "No graph loaded")
            return

        # Count disconnected nodes before cleanup
        disconnected_count = 0
        for node in self.current_graph.nodes.values():
            if (not node.is_arch_state and not node.is_uarch_state and
                not node.incoming_edges and not node.outgoing_edges):
                node_type = node.data.get('type', '')
                if node_type not in ['literal', 'isa_state', 'uarch_counter', 'hazard_detection_unit', 'stall_controller']:
                    disconnected_count += 1

        if disconnected_count == 0:
            self.status_var.set("No disconnected nodes found to clean up")
            return

        # Confirm cleanup
        result = messagebox.askyesno("Confirm Cleanup",
                                   f"Found {disconnected_count} disconnected nodes. Remove them?")
        if result:
            self.current_graph.cleanup_disconnected_nodes()
            self.current_graph.infer_uarch_time()
            self.update_display()
            self.update_graph_info()
            self.status_var.set(f"Removed {disconnected_count} disconnected nodes")

    def update_graph_info(self):
        """Update the graph information display."""
        self.graph_info_text.delete(1.0, tk.END)

        if self.current_graph:
            info = f"Nodes: {len(self.current_graph.nodes)}\n"
            info += f"Edges: {len(self.current_graph.edges)}\n"
            info += f"Max uarch time: {self.current_graph.get_max_uarch_time()}\n"

            # Count node types
            node_types = {}
            for node in self.current_graph.nodes.values():
                node_type = node.data.get('type', 'unknown')
                node_types[node_type] = node_types.get(node_type, 0) + 1

            info += f"Node types: {len(node_types)}"
        else:
            info = "No graph loaded"

        self.graph_info_text.insert(1.0, info)

    def update_selection_info(self):
        """Update the selection properties display."""
        self.selection_text.delete(1.0, tk.END)

        if not self.selected_nodes and not self.selected_edges:
            self.selection_text.insert(1.0, "No selection")
            return

        info = ""

        # Show selected nodes
        if self.selected_nodes:
            info += f"SELECTED NODES ({len(self.selected_nodes)}):\n"
            for node_id in self.selected_nodes:
                node = self.current_graph.nodes[node_id]
                info += f"\n{node_id}:\n"
                info += f"  Type: {node.data.get('type', 'unknown')}\n"
                info += f"  Display: {node.data.get('display_name', node_id)}\n"
                info += f"  Arch state: {node.is_arch_state}\n"
                info += f"  Uarch state: {node.is_uarch_state}\n"
                info += f"  Uarch time: {node.uarch_time}\n"
                info += f"  Latency: {node.latency} cycle(s)\n"

                if node.indexed_by:
                    info += f"  Indexed by: {node.indexed_by.id}\n"
                if node.used_as_index:
                    info += f"  Used as index: True\n"

                # Show some data properties
                if node.data:
                    for key, value in list(node.data.items())[:3]:
                        if key not in ['type', 'display_name']:
                            info += f"  {key}: {value}\n"

        # Show selected edges
        if self.selected_edges:
            if info:
                info += "\n"
            info += f"SELECTED EDGES ({len(self.selected_edges)}):\n"
            for edge_id in self.selected_edges:
                edge = self.current_graph.edges[edge_id]
                info += f"\n{edge_id}:\n"
                info += f"  Source: {edge.source.id}\n"
                info += f"  Target: {edge.target.id}\n"
                info += f"  Type: {edge.data.get('type', 'unknown')}\n"

                # Show some data properties
                if edge.data:
                    for key, value in list(edge.data.items())[:3]:
                        if key != 'type':
                            info += f"  {key}: {value}\n"

        self.selection_text.insert(1.0, info)

    def on_strategy_selected(self, event=None):
        """Handle optimization strategy selection."""
        strategy_name = self.strategy_var.get()
        strategy = next((s for s in self.optimization_strategies if s.name == strategy_name), None)

        if not strategy:
            return

        # Update button text based on strategy
        if strategy_name == "Multi-Stage Manual Pipelining":
            self.apply_button.config(text="Open Pipeline Wizard")
        else:
            self.apply_button.config(text="Apply Optimization")

        # Update description
        self.strategy_desc_text.configure(state=tk.NORMAL)
        self.strategy_desc_text.delete(1.0, tk.END)
        self.strategy_desc_text.insert(1.0, strategy.description)
        self.strategy_desc_text.configure(state=tk.DISABLED)

        # Clear existing parameter widgets
        for widget in self.params_frame.winfo_children():
            widget.destroy()

        # Create parameter input widgets
        self.param_vars = {}
        self.param_widgets = {}  # Store widget references for dynamic control
        for i, param in enumerate(strategy.parameters):
            param_frame = ttk.Frame(self.params_frame)
            param_frame.pack(fill=tk.X, pady=2)

            ttk.Label(param_frame, text=f"{param['name']}:").pack(side=tk.LEFT)

            if param['type'] == 'int':
                var = tk.IntVar(value=param['default'])
                spinbox = tk.Spinbox(param_frame, from_=param.get('min', 0),
                                   to=param.get('max', 100), textvariable=var, width=10)
                spinbox.pack(side=tk.RIGHT)
                self.param_widgets[param['name']] = spinbox  # Store widget reference
            elif param['type'] == 'file':
                var = tk.StringVar(value="Click to select file...")
                button = ttk.Button(param_frame, textvariable=var,
                                  command=lambda p=param, v=var: self._select_single_file(p, v))
                button.pack(side=tk.RIGHT)
            elif param['type'] == 'file_list':
                var = tk.StringVar(value="Click to select files...")
                button = ttk.Button(param_frame, textvariable=var,
                                  command=lambda p=param: self._select_files(p, var))
                button.pack(side=tk.RIGHT)
            elif param['type'] == 'selected_nodes':
                selection_count = len(self.selected_nodes)
                var = tk.StringVar(value=f"{selection_count} nodes selected")
                label = ttk.Label(param_frame, textvariable=var)
                label.pack(side=tk.RIGHT, padx=5)

                # Add helper button to show available nodes
                helper_btn = ttk.Button(param_frame, text="?", width=2,
                                       command=lambda p=param: self._show_node_selection_help(p))
                helper_btn.pack(side=tk.RIGHT)

                # Store reference to selected nodes
                setattr(var, '_selected_nodes', list(self.selected_nodes))
            elif param['type'] == 'selected_edges':
                selection_count = len(self.selected_edges)
                var = tk.StringVar(value=f"{selection_count} edges selected")
                button = ttk.Button(param_frame, textvariable=var, state=tk.DISABLED)
                button.pack(side=tk.RIGHT)
                # Store reference to selected edges
                setattr(var, '_selected_edges', list(self.selected_edges))
            elif param['type'] == 'selected_node':
                # Single node selection - shows button to pick from selected nodes
                var = tk.StringVar(value="Click to select from graph")
                desc = param.get('description', param['name'])
                button = ttk.Button(param_frame, textvariable=var,
                                  command=lambda p=param, v=var: self._select_single_node(p, v))
                button.pack(side=tk.RIGHT)
                # Store selected node ID
                setattr(var, '_selected_node_id', None)
            elif param['type'] == 'str':
                var = tk.StringVar(value=str(param['default']))
                entry = ttk.Entry(param_frame, textvariable=var, width=15)
                entry.pack(side=tk.RIGHT)
            elif param['type'] == 'bool':
                # Radio buttons for Yes/No
                var = tk.BooleanVar(value=param['default'])
                radio_frame = ttk.Frame(param_frame)
                radio_frame.pack(side=tk.RIGHT)
                ttk.Radiobutton(radio_frame, text="Yes", variable=var, value=True).pack(side=tk.LEFT, padx=5)
                ttk.Radiobutton(radio_frame, text="No", variable=var, value=False).pack(side=tk.LEFT, padx=5)
            elif param['type'] == 'choice':
                # Radio buttons for multiple choice
                var = tk.StringVar(value=param['default'])
                choices_frame = ttk.Frame(param_frame)
                choices_frame.pack(side=tk.RIGHT)
                for choice in param['choices']:
                    rb = ttk.Radiobutton(choices_frame, text=choice.capitalize(),
                                        variable=var, value=choice)
                    rb.pack(side=tk.LEFT, padx=5)
            else:
                var = tk.StringVar(value=str(param['default']))
                entry = ttk.Entry(param_frame, textvariable=var, width=15)
                entry.pack(side=tk.RIGHT)

            self.param_vars[param['name']] = var

        # Special handling: Dynamic enabling/disabling for "Change Operation Latency"
        if strategy.name == "Change Operation Latency":
            self._setup_latency_ui_dynamics()

    def _setup_latency_ui_dynamics(self):
        """Set up dynamic enabling/disabling of latency_value based on latency_type."""
        if 'latency_type' not in self.param_vars or 'latency_value' not in self.param_widgets:
            return

        latency_type_var = self.param_vars['latency_type']
        latency_value_widget = self.param_widgets['latency_value']

        def update_latency_value_state(*args):
            """Enable/disable latency_value spinbox based on latency_type selection."""
            if latency_type_var.get() == 'variable':
                # Grey out the spinbox when variable latency is selected
                latency_value_widget.config(state=tk.DISABLED)
            else:
                # Enable the spinbox when fixed latency is selected
                latency_value_widget.config(state=tk.NORMAL)

        # Add trace to watch for changes
        latency_type_var.trace_add('write', update_latency_value_state)

        # Set initial state
        update_latency_value_state()

    def update_parameter_display(self):
        """Update parameter displays when graph selection changes."""
        strategy_name = self.strategy_var.get()
        if not strategy_name or not self.param_vars:
            return

        strategy = next((s for s in self.optimization_strategies
                        if s.name == strategy_name), None)
        if not strategy:
            return

        for param in strategy.parameters:
            var = self.param_vars.get(param['name'])
            if not var:
                continue

            if param['type'] == 'selected_nodes':
                setattr(var, '_selected_nodes', list(self.selected_nodes))
                count = len(self.selected_nodes)
                var.set(f"{count} nodes selected")
            elif param['type'] == 'selected_edges':
                setattr(var, '_selected_edges', list(self.selected_edges))
                count = len(self.selected_edges)
                var.set(f"{count} edges selected")

    def _select_files(self, param: Dict, var: tk.StringVar):
        """Handle file selection for file_list parameters."""
        filenames = filedialog.askopenfilenames(
            title=f"Select files for {param['name']}",
            filetypes=[("ISA files", "*.isa"), ("All files", "*.*")]
        )

        if filenames:
            var.set(f"{len(filenames)} files selected")
            # Store actual filenames in a special attribute
            setattr(var, '_filenames', filenames)

    def _select_single_file(self, param: Dict, var: tk.StringVar):
        """Handle single file selection for file parameters."""
        # Determine file types based on parameter name
        param_name = param['name'].lower()
        if 'rgraph' in param_name:
            filetypes = [("Resource Graph files", "*.rgraph"), ("All files", "*.*")]
        elif 'spec' in param_name or 'alu' in param_name:
            filetypes = [("ALU spec files", "*.spec"), ("All files", "*.*")]
        else:
            filetypes = [("ISA files", "*.isa"), ("All files", "*.*")]

        filename = filedialog.askopenfilename(
            title=f"Select file for {param['name']}",
            filetypes=filetypes
        )

        if filename:
            import os
            var.set(os.path.basename(filename))
            # Store actual filename in a special attribute
            setattr(var, '_filename', filename)

    def _select_single_node(self, param: Dict, var: tk.StringVar):
        """Handle single node selection from currently selected nodes."""
        if not self.selected_nodes:
            messagebox.showinfo("Info",
                f"Please select a node from the graph first.\n\n"
                f"Click on a node to select it, then click this button again.\n\n"
                f"Parameter: {param.get('description', param['name'])}")
            return

        if len(self.selected_nodes) == 1:
            # Only one node selected, use it directly
            node_id = list(self.selected_nodes)[0]
            node = self.current_graph.nodes[node_id]
            var.set(f"{node_id}")
            setattr(var, '_selected_node_id', node_id)
        else:
            # Multiple nodes selected, show selection dialog
            dialog = tk.Toplevel(self.root)
            dialog.title(f"Select Node - {param['name']}")
            dialog.geometry("400x300")

            ttk.Label(dialog, text=f"Select one node for:\n{param.get('description', param['name'])}",
                     wraplength=350).pack(pady=10)

            # List of selected nodes
            listbox = tk.Listbox(dialog, height=10)
            listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

            for node_id in sorted(self.selected_nodes):
                node = self.current_graph.nodes[node_id]
                display_name = node.data.get('display_name', node_id) if node.data else node_id
                listbox.insert(tk.END, f"{node_id} - {display_name}")

            def on_select():
                selection = listbox.curselection()
                if selection:
                    idx = selection[0]
                    node_id = sorted(self.selected_nodes)[idx]
                    var.set(f"{node_id}")
                    setattr(var, '_selected_node_id', node_id)
                    dialog.destroy()

            ttk.Button(dialog, text="Select", command=on_select).pack(pady=5)

    def apply_optimization(self):
        """Apply the selected optimization strategy."""
        if not self.current_graph:
            messagebox.showerror("Error", "No graph loaded")
            return

        strategy_name = self.strategy_var.get()
        if not strategy_name:
            messagebox.showerror("Error", "No optimization strategy selected")
            return

        strategy = next((s for s in self.optimization_strategies if s.name == strategy_name), None)
        if not strategy:
            return

        try:
            # Collect parameters
            params = {}
            for param in strategy.parameters:
                var = self.param_vars[param['name']]
                if param['type'] == 'file':
                    if hasattr(var, '_filename'):
                        params[param['name']] = var._filename
                    else:
                        params[param['name']] = None
                elif param['type'] == 'file_list':
                    if hasattr(var, '_filenames'):
                        params[param['name']] = var._filenames
                    else:
                        params[param['name']] = []
                elif param['type'] == 'selected_nodes':
                    if hasattr(var, '_selected_nodes'):
                        params[param['name']] = var._selected_nodes
                    else:
                        params[param['name']] = []
                elif param['type'] == 'selected_edges':
                    if hasattr(var, '_selected_edges'):
                        params[param['name']] = var._selected_edges
                    else:
                        params[param['name']] = []
                elif param['type'] == 'selected_node':
                    if hasattr(var, '_selected_node_id'):
                        params[param['name']] = var._selected_node_id
                    else:
                        params[param['name']] = None
                else:
                    params[param['name']] = var.get()

            # Apply optimization
            result_graph = strategy.apply_function(self.current_graph.copy(), **params)

            # If this was a dry-run, don't treat a None result as an error
            if params.get('dry_run', False):
                messagebox.showinfo("Preview", "Dry run complete — no changes applied. See console for details.")
                return

            if result_graph:
                # For Multi-Stage Manual Pipelining, the wizard panel is opened
                # Don't add tree node yet - the panel will handle that
                if strategy_name == "Multi-Stage Manual Pipelining":
                    # Wizard panel opened successfully, don't add tree node yet
                    pass
                else:
                    # Don't re-infer timing - optimizations set their own timing
                    # Only infer missing timing if needed
                    result_graph.infer_uarch_time(force_reinfer=False)
                    # Add to tree instead of opening new window
                    node_label = f"{strategy_name}"
                    new_tree_node = self.add_tree_node(result_graph, node_label,
                                                       optimization_name=strategy_name,
                                                       optimization_params=params.copy())
                    # Update current graph to the result
                    self.current_tree_node = new_tree_node
                    self.current_graph = result_graph
                    self.graph_layout = self._create_initial_layout(result_graph)
                    self.clear_selection()
                    self.update_display(preserve_scroll=False)  # Auto-center for new optimized graph
                    self.update_graph_info()
            else:
                messagebox.showerror("Error", "Optimization failed")

        except Exception as e:
            messagebox.showerror("Error", f"Optimization failed: {e}")
            traceback.print_exc()

    def _apply_manual_pipelining(self, graph: ResourceGraph, selected_edges: List[str] = None, stage_name: str = "pipeline_stage") -> ResourceGraph:
        """Apply manual pipelining by inserting registers on selected edges."""
        if not selected_edges:
            return None  # No edges selected

        try:
            # Validate that selected edges form a valid pipeline cut
            if not self._validate_pipeline_cut(graph, selected_edges):
                print("ERROR: Selected edges do not form a valid pipeline cut!")
                print("A valid cut must separate the graph into distinct pipeline stages.")
                print("All dependency paths must cross the cut exactly once.")
                return None

            from core.resource_graph import Node, Edge

            # Track new nodes and edges created
            pipeline_registers = []

            # Insert pipeline register on each selected edge
            for edge_id in selected_edges:
                if edge_id not in graph.edges:
                    continue

                edge = graph.edges[edge_id]
                source_node = edge.source
                target_node = edge.target

                # Create pipeline register node
                reg_name = f"{source_node.id}_{stage_name}_reg"
                reg_data = {
                    'type': 'uarch_state',
                    'name': reg_name,
                    'display_name': reg_name,
                    'bit_width': 32,  # Default width
                    'stage_name': stage_name
                }

                pipeline_reg = Node(reg_name, reg_data, is_uarch_state=True)
                graph.add_node(pipeline_reg)
                pipeline_registers.append(pipeline_reg)

                # Store original edge data
                edge_data = edge.data.copy() if edge.data else {}

                # Remove original edge
                graph.remove_edge(edge_id)

                # Create new edges: source -> pipeline_reg -> target
                edge1 = Edge(source_node, pipeline_reg, data={'type': 'pipeline_stage', 'stage': stage_name})
                edge2 = Edge(pipeline_reg, target_node, data=edge_data)

                graph.add_edge(edge1)
                graph.add_edge(edge2)

                print(f"Inserted pipeline register {reg_name} on edge {source_node.id} -> {target_node.id}")

                # Clear timing of target node (but preserve timing from other pipeline registers)
                self._clear_timing_selectively(target_node, new_pipeline_registers=[pipeline_reg])

            # Set timing for pipeline registers - they hold values from their input stage
            # Pipeline registers are at the same time as their inputs, outputs are available next cycle
            for pipeline_reg in pipeline_registers:
                # Find the stage this register is in by looking at source timing
                source_time = 0
                source_node = None
                for edge in pipeline_reg.incoming_edges:
                    if edge.source.uarch_time is not None:
                        source_node = edge.source
                        source_time = edge.source.uarch_time
                        break

                # CRITICAL FIX: If source is a uarch_state node (like another pipeline register),
                # the new register should be at source_time + 1, not source_time
                if source_node and source_node.is_uarch_state:
                    pipeline_reg.uarch_time = source_time + 1
                    print(f"Set {pipeline_reg.id} timing to {pipeline_reg.uarch_time} (source {source_node.id} at {source_time} + 1 cycle)")
                else:
                    # For non-uarch-state sources, register is at same time as source
                    pipeline_reg.uarch_time = source_time
                    print(f"Set {pipeline_reg.id} timing to {pipeline_reg.uarch_time} (holds stage {source_time} value)")

            print(f"Manual pipelining: inserted {len(pipeline_registers)} pipeline registers")

            # Re-infer timing for all nodes after pipeline insertion
            # For manual pipelining, we need to be more aggressive about re-inference
            # to ensure register-to-register connections propagate correctly
            print("Re-inferring timing after manual pipelining...")

            # Force timing re-inference for nodes that might be affected by new pipeline registers
            affected_nodes = set()
            for pipeline_reg in pipeline_registers:
                # Find all nodes downstream of new pipeline registers
                for edge in pipeline_reg.outgoing_edges:
                    self._collect_affected_nodes(edge.target, affected_nodes)

            # Clear timing for affected nodes to ensure fresh inference
            for node_id in affected_nodes:
                if node_id in graph.nodes:
                    node = graph.nodes[node_id]
                    if not node.is_uarch_state or node in pipeline_registers:
                        # Clear timing for non-uarch-state nodes and new pipeline registers
                        node.uarch_time = None

            if affected_nodes:
                print(f"Cleared timing for {len(affected_nodes)} affected nodes for fresh inference")

            graph.infer_uarch_time(force_reinfer=False)


            return graph

        except Exception as e:
            print(f"Manual pipelining failed: {e}")
            return None

    def _clear_timing_recursively(self, node):
        """Clear timing for a node and all nodes that depend on it."""
        if node.uarch_time is None:
            return  # Already cleared

        print(f"Clearing timing for {node.id} and its dependencies")
        node.uarch_time = None

        # Recursively clear timing for all nodes that have this node as input
        for edge in node.outgoing_edges:
            self._clear_timing_recursively(edge.target)

    def _clear_timing_selectively(self, node, new_pipeline_registers=None):
        """
        Clear timing selectively to avoid disrupting existing pipeline registers.

        This is more conservative than _clear_timing_recursively and preserves
        timing for existing pipeline infrastructure during iterative pipelining.
        """
        if node.uarch_time is None:
            return  # Already cleared

        # Don't clear timing for existing pipeline registers unless they're in the new set
        if node.data.get('type') == 'pipeline_register':
            if new_pipeline_registers and node not in new_pipeline_registers:
                print(f"Preserving timing for existing pipeline register {node.id}")
                return

        # Don't clear timing for uarch_state nodes that have explicit timing set
        if node.is_uarch_state and node.uarch_time is not None:
            # Only clear if this is a new pipeline register we just created
            if new_pipeline_registers and node in new_pipeline_registers:
                pass  # Allow clearing
            else:
                print(f"Preserving timing for uarch_state node {node.id}")
                return

        print(f"Selectively clearing timing for {node.id}")
        node.uarch_time = None

        # Recursively clear timing for dependencies, but preserve pipeline infrastructure
        for edge in node.outgoing_edges:
            self._clear_timing_selectively(edge.target, new_pipeline_registers)

    def _collect_affected_nodes(self, node, affected_nodes):
        """Collect all nodes that might be affected by new pipeline register timing."""
        if node.id in affected_nodes:
            return  # Already visited

        affected_nodes.add(node.id)

        # Follow outgoing edges to find all downstream nodes
        for edge in node.outgoing_edges:
            self._collect_affected_nodes(edge.target, affected_nodes)

    def _validate_pipeline_cut(self, graph, selected_edge_ids):
        """
        Validate that selected edges form a valid pipeline cut.

        A valid cut should separate the graph into two parts where:
        1. No uncut edges cross from the source side to the target side
        2. The cut creates a clean timing boundary
        """
        if not selected_edge_ids:
            return False

        # Work on a copy to avoid modifying the original graph during validation
        validation_graph = graph.copy()
        selected_edges = [validation_graph.edges[edge_id] for edge_id in selected_edge_ids if edge_id in validation_graph.edges]

        print(f"Pipeline cut validation: checking {len(selected_edge_ids)} selected edges")

        # Get current timing to understand current stage assignments
        validation_graph.infer_uarch_time()

        # Find all nodes that will be on the "source side" vs "target side" of the cut
        #
        # Key insight: A valid pipeline cut means inserting pipeline registers on the
        # selected edges. The cut sources produce values that get latched, and the cut
        # targets consume those latched values.
        #
        # Stage assignment:
        # - Later stage: cut targets + everything forward-reachable from them
        # - Earlier stage: everything else
        #
        # This means the cut sources and their dependencies are in the earlier stage.

        cut_sources = set()
        cut_targets = set()

        for edge in selected_edges:
            cut_sources.add(edge.source.id)
            cut_targets.add(edge.target.id)

        # Later stage: everything that depends on the cut targets
        later_stage_nodes = self._find_forward_reachable(validation_graph, cut_targets)

        # Earlier stage: everything else (includes cut sources and all their dependencies)
        earlier_stage_nodes = set(validation_graph.nodes.keys()) - later_stage_nodes


        # Check for incomplete cuts: find edges that cross the cut boundary but aren't selected
        # IMPORTANT: We only care about edges that represent data dependencies on computed values.
        # Edges from architectural state nodes that are being READ (not written) don't need to be cut,
        # because they're reading the initial state, not waiting for a computation to complete.
        uncut_crossing_edges = []

        for edge_id, edge in validation_graph.edges.items():
            if edge_id in selected_edge_ids:
                continue  # This edge is being cut

            # Check if this edge crosses from earlier stage to later stage
            source_in_earlier = edge.source.id in earlier_stage_nodes
            target_in_later = edge.target.id in later_stage_nodes

            if source_in_earlier and target_in_later:
                # This edge crosses the boundary, but should it be cut?
                #
                # Key insight: We only need to cut edges that represent data dependencies on
                # COMPUTED values. Edges from sources that are constants or initial state
                # don't need to be cut.
                #
                # Don't cut if:
                # - Source is arch state only being READ (no writes in earlier stage)
                # - Source is a constant (no inputs)
                # - Source has no computation dependencies in the earlier stage

                source_node = edge.source

                # Check if this is an architectural state node
                if source_node.is_arch_state:
                    # Is this arch state being WRITTEN in the earlier stage?
                    # (i.e., does it have assignment edges coming from earlier stage nodes?)
                    has_write_in_earlier = any(
                        e.data.get('type') == 'assignment' and
                        e.source.id in earlier_stage_nodes
                        for e in source_node.incoming_edges
                    )

                    # If there's no write to this arch state in the earlier stage,
                    # then any read from it is reading initial state, not a computed value.
                    # These edges don't need to be cut.
                    if not has_write_in_earlier:
                        continue

                # Check if source is a constant (no inputs at all)
                if len(source_node.incoming_edges) == 0:
                    # Constants/variables with no inputs are available in all stages
                    continue

                # This edge crosses the cut boundary and represents a true data dependency
                uncut_crossing_edges.append(edge)

        # Report validation results
        print(f"Pipeline cut validation: cutting {len(selected_edges)} edges")
        print(f"Earlier stage: {len(earlier_stage_nodes)} nodes")
        print(f"Later stage: {len(later_stage_nodes)} nodes")

        # Debug: show what's in later stage
        if len(later_stage_nodes) < 20:
            print(f"Later stage nodes: {sorted(later_stage_nodes)}")

        # Debug: check if cut targets are arch state
        for target_id in cut_targets:
            if target_id in validation_graph.nodes:
                node = validation_graph.nodes[target_id]
                print(f"  Cut target '{target_id}': is_arch_state={node.is_arch_state}")

        # Debug: check if problematic nodes are in later stage
        problem_nodes = ['(pc + 4)', '(pc_plus_4 + branch_offset)', 'pc_mux', '4']
        for node_id in problem_nodes:
            if node_id in later_stage_nodes:
                print(f"  DEBUG: {node_id} is in LATER stage (unexpected?)")
            elif node_id in earlier_stage_nodes:
                print(f"  DEBUG: {node_id} is in EARLIER stage (expected)")

        if uncut_crossing_edges:
            print(f"ERROR: Incomplete cut detected!")
            print(f"These {len(uncut_crossing_edges)} edges also need to be cut:")
            for edge in uncut_crossing_edges:
                source_time = edge.source.uarch_time or 0
                target_time = edge.target.uarch_time or 0
                print(f"  - {edge.source.id} -> {edge.target.id} (time {source_time} -> {target_time})")
            print("Select these edges and try again for a complete cut.")
            return False

        print("✓ Cut appears to be complete - no uncut edges cross the boundary")
        return True

    def _find_backward_reachable(self, graph, start_nodes):
        """Find all nodes reachable by following edges backward from start_nodes."""
        visited = set(start_nodes)
        stack = list(start_nodes)

        while stack:
            current_id = stack.pop()
            if current_id not in graph.nodes:
                continue

            current_node = graph.nodes[current_id]

            # Follow incoming edges (backward)
            for edge in current_node.incoming_edges:
                source_id = edge.source.id
                if source_id not in visited:
                    visited.add(source_id)
                    stack.append(source_id)

        return visited

    def _find_forward_reachable(self, graph, start_nodes):
        """
        Find all nodes reachable by following edges forward from start_nodes.

        Special handling: If start_nodes are architectural state nodes/writes,
        don't follow edges that read FROM them (since those reads happen at the
        beginning of the instruction, not after the write).
        """
        visited = set(start_nodes)
        stack = list(start_nodes)

        def is_arch_state_write(node):
            """Check if a node is a write to architectural state."""
            # Direct arch state nodes
            if node.is_arch_state:
                return True
            # Array access nodes like rf[rd]_wr, pc_wr (assignments to arch state)
            # Check if this is a write by seeing if it's named with _wr suffix
            if '_wr' in node.id:
                return True
            return False

        while stack:
            current_id = stack.pop()
            if current_id not in graph.nodes:
                continue

            current_node = graph.nodes[current_id]

            # Follow outgoing edges (forward)
            for edge in current_node.outgoing_edges:
                edge_type = edge.data.get('type', '') if edge.data else ''

                # If this is an arch state write node, don't follow read edges
                # (reads happen at the start, before writes complete)
                if is_arch_state_write(current_node):
                    # Skip edges that read FROM this arch state
                    if edge_type in ['operand', 'array_index', 'bit_access']:
                        continue

                target_id = edge.target.id
                if target_id not in visited:
                    visited.add(target_id)
                    stack.append(target_id)

        return visited

    def _apply_multi_stage_pipelining(self, graph: ResourceGraph,
                                     num_stages: int = 2,
                                     stage_names: str = "fetch,decode") -> ResourceGraph:
        """
        Apply multi-stage manual pipelining with a side panel for edge selection.

        Shows a panel where users can select edges for each stage, then applies all at once.

        Returns a special marker object to indicate the wizard was opened successfully.
        """
        # Parse stage names
        stage_name_list = [name.strip() for name in stage_names.split(',')]
        if len(stage_name_list) < num_stages:
            # Pad with default names if not enough provided
            for i in range(len(stage_name_list), num_stages):
                stage_name_list.append(f"stage_{i+1}")

        # Show multi-stage pipelining panel
        self._show_multi_stage_panel(graph, num_stages, stage_name_list)

        # Return the graph to indicate success (the panel will handle the actual application)
        # We return the graph so that apply_optimization() doesn't show an error dialog
        return graph

    def _count_existing_pipeline_stages(self, graph: ResourceGraph) -> int:
        """Count how many pipeline stages have already been added to the graph."""
        # Count unique stage names from pipeline register nodes
        stage_names = set()
        for node in graph.nodes.values():
            if node.data.get('type') == 'uarch_state' and 'stage_name' in node.data:
                stage_names.add(node.data['stage_name'])
        return len(stage_names)

    def _add_hazard_detection_to_stage(self, graph: ResourceGraph, stage_name: str):
        """
        Add hazard detection for a pipeline stage using the enhanced hazard detection
        from pipelining_optimization.py.
        """
        try:
            from opt.pipeline.pipelining_optimization import DependencyAnalysis, PipelineTransform, PipelineStageSpec

            # Analyze dependencies
            dep_analysis = DependencyAnalysis(graph)
            analysis = dep_analysis.analyze_dependencies()

            if not analysis['potential_hazards']:
                print(f"  No hazards detected for stage {stage_name}")
                return

            print(f"  Found {len(analysis['potential_hazards'])} potential hazards")

            # Create a pipeline stage spec for this stage
            stage_spec = PipelineStageSpec(
                cut_location=stage_name,
                stage_name=stage_name,
                description=f"Pipeline stage {stage_name}"
            )

            # Add hazard detectors based on analysis
            for hazard in analysis['potential_hazards']:
                if hazard['type'] == 'RAW' and hazard['condition']:
                    stage_spec.add_hazard_detector(
                        source_resource=hazard['resource'],
                        target_resource=hazard['resource'],
                        hazard_type='RAW',
                        check_condition=hazard['condition']
                    )

            if not stage_spec.hazard_detectors:
                print(f"  No actionable hazards for stage {stage_name}")
                return

            # Create pipeline transform to generate hardware
            transform = PipelineTransform(graph)
            transform.pipeline_prefix = f"HAZARD_{stage_name}"
            transform.stage_counter = 0

            # Generate hazard detection hardware
            hazard_unit, stall_nodes = transform._create_hazard_detection_unit(stage_spec)
            stall_controller = transform._create_stall_controller(stage_spec, hazard_unit)

            # Connect stall signals to controller
            for stall_node in stall_nodes:
                transform._connect_stall_to_controller(stall_node, stall_controller)

            print(f"  Added {len(stall_nodes)} hazard detectors with hardware generation")

        except Exception as e:
            print(f"  Warning: Could not add hazard detection: {e}")
            # Non-fatal - pipelining still works without hazard detection

    def _show_multi_stage_panel(self, graph: ResourceGraph, num_stages: int, stage_names: List[str]):
        """Show the multi-stage pipelining panel in the right pane (integrated, non-modal)."""

        # Clear existing panel contents if visible
        if self.multistage_panel_visible:
            self._clear_pipeline_opt_frame()
            self.multistage_panel_visible = False

        # For N stages, we need N-1 pipeline cuts (between stages)
        num_cuts = num_stages - 1

        # Use the integrated pipeline_opt_frame instead of Toplevel
        panel = self.pipeline_opt_frame

        # Store reference (now points to the frame, not a window)
        self.multistage_panel = panel
        self.multistage_panel_visible = True

        # Initialize edge selections for cuts (N-1 cuts for N stages)
        self.multistage_edges_per_stage = {i: [] for i in range(num_cuts)}
        self.multistage_current_stage = 0
        self.multistage_graph = graph
        self.multistage_num_stages = num_stages
        self.multistage_num_cuts = num_cuts
        self.multistage_stage_names = stage_names

        # Create a scrollable container for the entire pipeline builder
        outer_canvas = tk.Canvas(panel, highlightthickness=0)
        outer_scrollbar = ttk.Scrollbar(panel, orient="vertical", command=outer_canvas.yview)
        outer_scrollable = ttk.Frame(outer_canvas)

        outer_scrollable.bind(
            "<Configure>",
            lambda e: outer_canvas.configure(scrollregion=outer_canvas.bbox("all"))
        )

        outer_canvas.create_window((0, 0), window=outer_scrollable, anchor="nw")
        outer_canvas.configure(yscrollcommand=outer_scrollbar.set)

        outer_scrollbar.pack(side="right", fill="y")
        outer_canvas.pack(side="left", fill="both", expand=True)

        # Bind canvas width to frame width
        def _configure_canvas(event):
            outer_canvas.itemconfig(outer_canvas.find_withtag("all")[0], width=event.width)
        outer_canvas.bind("<Configure>", _configure_canvas)

        # Enable mousewheel scrolling for the outer canvas
        def _on_outer_mousewheel(event):
            outer_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        def _on_outer_scroll_up(event):
            outer_canvas.yview_scroll(-1, "units")

        def _on_outer_scroll_down(event):
            outer_canvas.yview_scroll(1, "units")

        # Bind to canvas and scrollable frame
        outer_canvas.bind("<MouseWheel>", _on_outer_mousewheel)
        outer_scrollable.bind("<MouseWheel>", _on_outer_mousewheel)
        # Linux scroll events
        outer_canvas.bind("<Button-4>", _on_outer_scroll_up)
        outer_canvas.bind("<Button-5>", _on_outer_scroll_down)
        outer_scrollable.bind("<Button-4>", _on_outer_scroll_up)
        outer_scrollable.bind("<Button-5>", _on_outer_scroll_down)

        # Helper to bind mousewheel to all children recursively
        def _bind_mousewheel_recursive(widget):
            widget.bind("<MouseWheel>", _on_outer_mousewheel)
            widget.bind("<Button-4>", _on_outer_scroll_up)
            widget.bind("<Button-5>", _on_outer_scroll_down)
            for child in widget.winfo_children():
                _bind_mousewheel_recursive(child)

        # Create cut frames (N-1 cuts for N stages)
        self.multistage_stage_frames = []
        self.multistage_stage_labels = []

        for i in range(num_cuts):
            # Cut is between stage i and stage i+1
            before_stage = stage_names[i]
            after_stage = stage_names[i+1]

            cut_frame = ttk.LabelFrame(outer_scrollable,
                                      text=f"Cut {i+1}: {before_stage}→{after_stage}")
            cut_frame.pack(fill=tk.X, padx=2, pady=2)

            # Edge count label
            edge_label = ttk.Label(cut_frame, text="0 edges", font=("Arial", 7))
            edge_label.pack(anchor=tk.W, padx=2, pady=1)

            # Button frame for side-by-side layout
            btn_frame = ttk.Frame(cut_frame)
            btn_frame.pack(fill=tk.X, padx=2, pady=1)

            # Select button (left)
            select_btn = ttk.Button(btn_frame, text="Select",
                                   command=lambda idx=i: self._activate_stage_selection(idx))
            select_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 1))

            # Line Drag button (middle)
            line_btn = ttk.Button(btn_frame, text="Line",
                                 command=lambda idx=i: self._activate_line_drag_mode(idx))
            line_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)

            # Clear button (right)
            clear_btn = ttk.Button(btn_frame, text="Clear",
                                  command=lambda idx=i: self._clear_stage_selection(idx))
            clear_btn.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(1, 0))

            self.multistage_stage_frames.append(cut_frame)
            self.multistage_stage_labels.append(edge_label)

        # Bottom buttons
        button_frame = ttk.Frame(outer_scrollable)
        button_frame.pack(fill=tk.X, padx=2, pady=5)

        apply_btn = ttk.Button(button_frame, text="Apply",
                              command=self._apply_multistage_pipeline)
        apply_btn.pack(side=tk.LEFT, padx=2)

        cancel_btn = ttk.Button(button_frame, text="Cancel",
                               command=self._cancel_multistage_pipeline)
        cancel_btn.pack(side=tk.RIGHT, padx=2)

        # Bind mousewheel to all children after they're created
        _bind_mousewheel_recursive(outer_scrollable)

    def _activate_stage_selection(self, stage_index: int):
        """Activate edge selection mode for a specific cut."""
        # Exit line drag mode if active
        if self.line_drag_mode:
            self.line_drag_mode = False
            if self.line_drag_temp_line:
                self.canvas.delete(self.line_drag_temp_line)
                self.line_drag_temp_line = None
            self.line_drag_start = None
            self._restore_normal_canvas_bindings()

        self.multistage_current_stage = stage_index
        # Cut is between stage_index and stage_index+1
        before_stage = self.multistage_stage_names[stage_index]
        after_stage = self.multistage_stage_names[stage_index + 1]
        self.status_var.set(f"CLICK MODE: Click edges for Cut {stage_index + 1} ({before_stage}→{after_stage}). Click 'Line' for drag mode.")

        # Highlight the active cut in the panel
        for i, frame in enumerate(self.multistage_stage_frames):
            if i == stage_index:
                frame.configure(relief=tk.RAISED, borderwidth=3)
            else:
                frame.configure(relief=tk.GROOVE, borderwidth=2)

    def _clear_stage_selection(self, stage_index: int):
        """Clear edge selection for a specific stage."""
        self.multistage_edges_per_stage[stage_index] = []
        self._update_stage_label(stage_index)
        self.status_var.set(f"Cleared edges for stage {stage_index + 1}")
        self.update_display()  # Refresh to remove colored edges

    def _activate_line_drag_mode(self, stage_index: int):
        """Activate line drag selection mode for a specific cut."""
        self.multistage_current_stage = stage_index
        self.line_drag_mode = True

        # Cut is between stage_index and stage_index+1
        before_stage = self.multistage_stage_names[stage_index]
        after_stage = self.multistage_stage_names[stage_index + 1]
        self.status_var.set(f"LINE DRAG MODE: Drag a line across edges for Cut {stage_index + 1} ({before_stage}→{after_stage})")

        # Highlight the active cut in the panel
        for i, frame in enumerate(self.multistage_stage_frames):
            if i == stage_index:
                frame.configure(relief=tk.RAISED, borderwidth=3)
            else:
                frame.configure(relief=tk.GROOVE, borderwidth=2)

        # Bind mouse events for line dragging
        self.canvas.bind("<Button-1>", self._line_drag_start)
        self.canvas.bind("<B1-Motion>", self._line_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._line_drag_end)

    def _line_drag_start(self, event):
        """Start drawing a line for edge selection."""
        if not self.line_drag_mode:
            return

        # Get canvas coordinates (accounting for scroll)
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        self.line_drag_start = (canvas_x, canvas_y)

        # Create temporary line
        if self.line_drag_temp_line:
            self.canvas.delete(self.line_drag_temp_line)
        self.line_drag_temp_line = self.canvas.create_line(
            canvas_x, canvas_y, canvas_x, canvas_y,
            fill="#FF00FF", width=3, dash=(5, 5)
        )

    def _line_drag_motion(self, event):
        """Update the temporary line as user drags."""
        if not self.line_drag_mode or not self.line_drag_start:
            return

        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # Update temporary line
        if self.line_drag_temp_line:
            self.canvas.coords(
                self.line_drag_temp_line,
                self.line_drag_start[0], self.line_drag_start[1],
                canvas_x, canvas_y
            )

    def _line_drag_end(self, event):
        """End line drag and select all intersecting edges."""
        if not self.line_drag_mode or not self.line_drag_start:
            return

        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        line_end = (canvas_x, canvas_y)

        # Find all edges that intersect with the drawn line
        intersecting_edges = self._find_edges_intersecting_line(
            self.line_drag_start, line_end
        )

        # Add intersecting edges to the current stage selection
        for edge_id in intersecting_edges:
            if edge_id not in self.multistage_edges_per_stage[self.multistage_current_stage]:
                self.multistage_edges_per_stage[self.multistage_current_stage].append(edge_id)

        # Update display
        self._update_stage_label(self.multistage_current_stage)

        # Show count and remind user they're still in line drag mode
        before_stage = self.multistage_stage_names[self.multistage_current_stage]
        after_stage = self.multistage_stage_names[self.multistage_current_stage + 1]
        total_edges = len(self.multistage_edges_per_stage[self.multistage_current_stage])
        self.status_var.set(f"Added {len(intersecting_edges)} edges ({total_edges} total). LINE DRAG MODE active for Cut {self.multistage_current_stage + 1}. Click 'Select' to switch to click mode.")

        # Clean up temporary line but stay in line drag mode
        if self.line_drag_temp_line:
            self.canvas.delete(self.line_drag_temp_line)
            self.line_drag_temp_line = None
        self.line_drag_start = None

        # Stay in line drag mode for more drags - don't exit!
        # User can switch to Select mode by clicking Select button

        # Refresh display to show selected edges
        self.update_display()

    def _find_edges_intersecting_line(self, line_start, line_end):
        """Find all graph edges that intersect with the user-drawn line."""
        intersecting = []

        if not self.current_graph or not self.graph_layout:
            return intersecting

        # Get positions of all nodes from the current layout
        positions = self.graph_layout.node_positions

        for edge_id, edge in self.current_graph.edges.items():
            # Get edge endpoints from node positions
            source_pos = positions.get(edge.source.id)
            target_pos = positions.get(edge.target.id)

            if not source_pos or not target_pos:
                continue

            # Check if lines intersect
            if self._lines_intersect(
                line_start[0], line_start[1], line_end[0], line_end[1],
                source_pos.x, source_pos.y, target_pos.x, target_pos.y
            ):
                intersecting.append(edge_id)

        return intersecting

    def _lines_intersect(self, x1, y1, x2, y2, x3, y3, x4, y4):
        """Check if line segment (x1,y1)-(x2,y2) intersects with (x3,y3)-(x4,y4)."""
        # Using the cross product method
        def ccw(ax, ay, bx, by, cx, cy):
            return (cy - ay) * (bx - ax) > (by - ay) * (cx - ax)

        # Two segments intersect if they straddle each other
        return (ccw(x1, y1, x3, y3, x4, y4) != ccw(x2, y2, x3, y3, x4, y4) and
                ccw(x1, y1, x2, y2, x3, y3) != ccw(x1, y1, x2, y2, x4, y4))

    def _restore_normal_canvas_bindings(self):
        """Restore normal canvas mouse bindings after line drag mode."""
        # Restore normal click behavior
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

    def _update_stage_label(self, stage_index: int):
        """Update the edge count label for a stage."""
        count = len(self.multistage_edges_per_stage[stage_index])
        self.multistage_stage_labels[stage_index].config(text=f"{count} edges selected")

    def _apply_multistage_pipeline(self):
        """Apply all pipeline cuts at once."""
        try:
            # Validate that all cuts have edges selected
            empty_cuts = []
            for i in range(self.multistage_num_cuts):
                edges = self.multistage_edges_per_stage[i]
                if not edges:
                    before = self.multistage_stage_names[i]
                    after = self.multistage_stage_names[i+1]
                    empty_cuts.append(f"Cut {i+1} (between '{before}' and '{after}')")

            if empty_cuts:
                messagebox.showwarning("Incomplete Selection",
                                      f"The following cuts have no edges selected:\n" +
                                      "\n".join(empty_cuts) +
                                      "\n\nPlease select edges for all cuts.")
                return

            print("="*80)
            print("APPLYING MULTI-STAGE PIPELINE")
            print("="*80)
            print(f"{self.multistage_num_stages} stages with {self.multistage_num_cuts} cuts")

            # Create a working copy of the graph
            import copy
            working_graph = copy.deepcopy(self.multistage_graph)

            # Apply all cuts at once using the new atomic method
            # This avoids exposing intermediate state and confusing error messages
            from opt.pipeline.pipelining_optimization import PipelineTransform

            # Prepare cut specifications
            cut_specs = []
            for i in range(self.multistage_num_cuts):
                before_stage = self.multistage_stage_names[i]
                after_stage = self.multistage_stage_names[i+1]
                edges = self.multistage_edges_per_stage[i]

                print(f"\nCut {i+1}: {before_stage} → {after_stage} ({len(edges)} edges)")
                for edge_id in edges:
                    # Try to find the edge in the working graph to show source->target
                    if edge_id in working_graph.edges:
                        edge = working_graph.edges[edge_id]
                        print(f"  - {edge.source.id} -> {edge.target.id} (edge_id: {edge_id})")
                    else:
                        print(f"  - {edge_id}")

                cut_specs.append({
                    'edges': edges,
                    'before_stage': before_stage,
                    'after_stage': after_stage
                })

            # Apply all stages atomically
            print(f"\nApplying all {len(cut_specs)} pipeline stages atomically...")
            transform = PipelineTransform(working_graph)
            success = transform.add_multiple_pipeline_stages(cut_specs)

            if not success:
                messagebox.showerror("Pipeline Error",
                                    "Failed to apply multi-stage pipeline.\n" +
                                    "Check console for details.")
                return

            print(f"\n{'='*80}")
            print("MULTI-STAGE PIPELINING COMPLETE")
            print(f"{'='*80}")
            print(f"Created {self.multistage_num_stages} pipeline stages with {self.multistage_num_cuts} cuts:")
            for i in range(self.multistage_num_cuts):
                before = self.multistage_stage_names[i]
                after = self.multistage_stage_names[i+1]
                edge_count = len(self.multistage_edges_per_stage[i])
                print(f"  Cut {i+1}: {before} → {after} ({edge_count} pipeline registers)")
            print(f"\nTotal nodes: {len(working_graph.nodes)}")
            print(f"Pipeline depth: {working_graph.get_max_uarch_time() + 1} cycles")
            print(f"{'='*80}")

            # Analyze hazards and let user choose resolution strategies
            print(f"\n{'='*80}")
            print("HAZARD ANALYSIS")
            print(f"{'='*80}")

            from opt.pipeline.hazard_resolution import HazardAnalyzer, HazardResolver

            analyzer = HazardAnalyzer(working_graph, pc_name='pc')
            analyzer.identify_pipeline_stages()
            hazards = analyzer.analyze_hazards()

            if hazards:
                print(f"Found {len(hazards)} potential hazards")

                # Show hazard resolution panel integrated into the right pane
                # Store state for the hazard resolution step
                self._pending_pipelined_graph = working_graph
                self._pending_hazards = hazards
                self._show_hazard_resolution_panel(hazards)
                return  # Wait for user to apply hazard resolutions
            else:
                print("No hazards detected - pipeline has no data dependencies")

            # No hazards, complete the pipeline immediately
            self._complete_pipeline_application(working_graph, [])

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"\nError during multi-stage pipelining: {e}")
            messagebox.showerror("Pipeline Error",
                               f"Multi-stage pipelining failed:\n{str(e)}\n\n" +
                               "Check console for details.")
            return

    def _show_hazard_resolution_panel(self, hazards):
        """Show hazard resolution options in the integrated right panel."""
        self._clear_pipeline_opt_frame()

        panel = self.pipeline_opt_frame

        # Create a scrollable container
        outer_canvas = tk.Canvas(panel, highlightthickness=0)
        outer_scrollbar = ttk.Scrollbar(panel, orient="vertical", command=outer_canvas.yview)
        outer_scrollable = ttk.Frame(outer_canvas)

        outer_scrollable.bind(
            "<Configure>",
            lambda e: outer_canvas.configure(scrollregion=outer_canvas.bbox("all"))
        )

        outer_canvas.create_window((0, 0), window=outer_scrollable, anchor="nw")
        outer_canvas.configure(yscrollcommand=outer_scrollbar.set)

        outer_scrollbar.pack(side="right", fill="y")
        outer_canvas.pack(side="left", fill="both", expand=True)

        # Bind canvas width
        def _configure_canvas(event):
            outer_canvas.itemconfig(outer_canvas.find_withtag("all")[0], width=event.width)
        outer_canvas.bind("<Configure>", _configure_canvas)

        # Mousewheel scrolling
        def _on_mousewheel(event):
            outer_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        def _on_scroll_up(event):
            outer_canvas.yview_scroll(-1, "units")

        def _on_scroll_down(event):
            outer_canvas.yview_scroll(1, "units")

        def _bind_mousewheel_recursive(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            widget.bind("<Button-4>", _on_scroll_up)
            widget.bind("<Button-5>", _on_scroll_down)
            for child in widget.winfo_children():
                _bind_mousewheel_recursive(child)

        outer_canvas.bind("<MouseWheel>", _on_mousewheel)
        outer_canvas.bind("<Button-4>", _on_scroll_up)
        outer_canvas.bind("<Button-5>", _on_scroll_down)

        # Header
        header_frame = ttk.LabelFrame(outer_scrollable, text="Hazard Resolution")
        header_frame.pack(fill=tk.X, padx=2, pady=2)

        ttk.Label(header_frame, text=f"{len(hazards)} hazards found",
                 font=("Arial", 8, "bold")).pack(anchor=tk.W, padx=2)

        # Store resolution choices
        self._hazard_resolution_vars = {}

        # Create a frame for each hazard
        for i, hazard in enumerate(hazards):
            hazard_frame = ttk.LabelFrame(outer_scrollable, text=f"Hazard {i+1}")
            hazard_frame.pack(fill=tk.X, padx=2, pady=2)

            # Hazard description
            desc = f"{hazard.write_stage_name}→{hazard.read_stage_name}"
            ttk.Label(hazard_frame, text=desc, font=("Arial", 7)).pack(anchor=tk.W, padx=2)

            # Resource info
            resource_info = f"{hazard.resource}[{hazard.write_index_name}]→[{hazard.read_index_name}]"
            ttk.Label(hazard_frame, text=resource_info, font=("Arial", 6), foreground="gray").pack(anchor=tk.W, padx=2)

            # Resolution strategy radio buttons
            var = tk.StringVar(value="stall")
            self._hazard_resolution_vars[i] = var

            btn_frame = ttk.Frame(hazard_frame)
            btn_frame.pack(fill=tk.X, padx=2, pady=1)

            ttk.Radiobutton(btn_frame, text="Stall", variable=var, value="stall").pack(side=tk.LEFT)
            ttk.Radiobutton(btn_frame, text="Bypass", variable=var, value="bypass").pack(side=tk.LEFT)

        # Apply and Cancel buttons
        button_frame = ttk.Frame(outer_scrollable)
        button_frame.pack(fill=tk.X, padx=2, pady=5)

        apply_btn = ttk.Button(button_frame, text="Apply",
                              command=lambda: self._apply_hazard_resolutions(hazards))
        apply_btn.pack(side=tk.LEFT, padx=2)

        cancel_btn = ttk.Button(button_frame, text="Cancel",
                               command=self._cancel_hazard_resolution)
        cancel_btn.pack(side=tk.RIGHT, padx=2)

        _bind_mousewheel_recursive(outer_scrollable)

    def _apply_hazard_resolutions(self, hazards):
        """Apply the selected hazard resolutions."""
        from opt.pipeline.hazard_resolution import HazardResolver, HazardResolutionStrategy

        print(f"\n{'='*80}")
        print("APPLYING HAZARD RESOLUTIONS")
        print(f"{'='*80}")

        # Set resolution strategies based on user choices
        for i, hazard in enumerate(hazards):
            strategy_str = self._hazard_resolution_vars[i].get()
            if strategy_str == "stall":
                hazard.resolution = HazardResolutionStrategy.STALL
            elif strategy_str == "bypass":
                hazard.resolution = HazardResolutionStrategy.BYPASS
            else:
                hazard.resolution = HazardResolutionStrategy.NONE
            print(f"Hazard {i+1}: {strategy_str}")

        resolver = HazardResolver(self._pending_pipelined_graph)
        success = resolver.resolve_all_hazards(hazards)

        if success:
            print(f"Successfully applied all hazard resolutions")
        else:
            print(f"Warning: Some hazard resolutions failed")

        # Complete the pipeline application
        self._complete_pipeline_application(self._pending_pipelined_graph, hazards)

    def _cancel_hazard_resolution(self):
        """Cancel hazard resolution and abort pipeline operation."""
        self._clear_pipeline_opt_frame()
        self._pending_pipelined_graph = None
        self._pending_hazards = None
        self.status_var.set("Pipeline operation cancelled")
        messagebox.showinfo("Cancelled",
                          "Pipeline operation cancelled.\n\n" +
                          "Hazard resolutions were not applied.")

    def _complete_pipeline_application(self, working_graph, hazards):
        """Complete the pipeline application after hazard resolution."""
        import traceback
        try:
            print(f"\n{'='*80}")
            print("FINAL PIPELINE STATISTICS")
            print(f"{'='*80}")
            print(f"Total nodes: {len(working_graph.nodes)}")
            print(f"Pipeline depth: {working_graph.get_max_uarch_time() + 1} cycles")
            print(f"{'='*80}")

            # Add to tree instead of opening new window
            node_label = f"Multi-Stage Pipeline: {', '.join(self.multistage_stage_names)}"
            new_tree_node = self.add_tree_node(working_graph, node_label,
                                              optimization_name="Multi-Stage Manual Pipelining",
                                              optimization_params={
                                                  'num_stages': self.multistage_num_stages,
                                                  'stage_names': ', '.join(self.multistage_stage_names),
                                                  'edges_per_stage': dict(self.multistage_edges_per_stage)
                                              })
            # Update current graph to the result
            self.current_tree_node = new_tree_node
            self.current_graph = working_graph
            self.graph_layout = self._create_initial_layout(working_graph)
            self.clear_selection()
            self.update_display(preserve_scroll=False)  # Auto-center for new pipelined graph
            self.update_graph_info()

            # Close the multistage panel
            self._cancel_multistage_pipeline()

            # Show success message
            hazard_summary = f"\nHazards: {len(hazards)} detected" if hazards else "\nNo hazards detected"
            messagebox.showinfo("Success",
                              f"Multi-stage pipelining complete!\n\n" +
                              f"Created {self.multistage_num_stages} stages with {self.multistage_num_cuts} cuts\n" +
                              f"Stages: {', '.join(self.multistage_stage_names)}" +
                              hazard_summary + "\n\n" +
                              f"Pipeline depth: {working_graph.get_max_uarch_time()} cycles\n" +
                              f"Total nodes: {len(working_graph.nodes)}")

        except Exception as e:
            print(f"ERROR: Multi-stage pipelining failed: {e}")
            traceback.print_exc()
            messagebox.showerror("Error",
                               f"Multi-stage pipelining failed:\n{str(e)}\n\n" +
                               "Check console for details.")
            return

    def _cancel_multistage_pipeline(self):
        """Cancel multi-stage pipelining and clear panel."""
        # Clean up line drag mode if active
        if self.line_drag_mode:
            self.line_drag_mode = False
            if self.line_drag_temp_line:
                self.canvas.delete(self.line_drag_temp_line)
                self.line_drag_temp_line = None
            self.line_drag_start = None
            self._restore_normal_canvas_bindings()

        self._clear_pipeline_opt_frame()
        self.multistage_panel = None
        self.multistage_panel_visible = False
        self.multistage_edges_per_stage = {}
        self.status_var.set("Multi-stage pipelining cancelled")

    def _clear_pipeline_opt_frame(self):
        """Clear all widgets from the pipeline optimization frame."""
        for widget in self.pipeline_opt_frame.winfo_children():
            widget.destroy()

    def _apply_alu_integration(self, graph: ResourceGraph,
                               selected_nodes: List[str] = None,
                               alu_spec_file: str = '') -> ResourceGraph:
        """Apply ALU integration optimization.

        Replaces the selected operation nodes with a shared ALU module
        defined by the .spec file.  Raises ValueError if any selected
        node fails validation (the outer handler shows this in a dialog).
        """
        if not selected_nodes or len(selected_nodes) < 2:
            raise ValueError("Select at least 2 operation nodes from the graph")

        if not alu_spec_file:
            raise ValueError("ALU spec file required — click the file button to select a .spec file")

        from core.alu_spec_parser import parse_alu_spec_file
        from opt.alu_integration import apply_alu_integration

        alu_specs = parse_alu_spec_file(alu_spec_file)
        if not alu_specs:
            raise ValueError(f"No alu_module declarations found in '{alu_spec_file}'")

        # apply_alu_integration raises ValueError with a specific message
        # if any node fails validation — let it propagate to the dialog.
        success = apply_alu_integration(graph, alu_specs[0], selected_nodes)
        return graph if success else None

    def _apply_instruction_merging(self, graph: ResourceGraph, instruction_files: List[str]) -> ResourceGraph:
        """Apply instruction merging optimization."""
        if not instruction_files:
            return None

        # Create instruction mapping from provided files
        instruction_dict = {}
        for filename in instruction_files:
            import os
            base_name = os.path.splitext(os.path.basename(filename))[0]
            if base_name.endswith('_instr'):
                instr_name = base_name[:-6]
            else:
                instr_name = base_name
            instruction_dict[instr_name] = filename

        # If there's a currently loaded graph that looks like a single instruction,
        # include it in the merge by writing it to a temporary ISA file
        if graph:
            # Check if this is a single instruction (no instruction_enable nodes) or already merged
            enable_nodes = [node for node in graph.nodes.values()
                          if node.data.get('type') == 'instruction_enable']

            if not enable_nodes:
                # Current graph appears to be a single instruction - include it in merge
                import tempfile
                import os

                # Create a temporary ISA file for the current graph
                # We'll reconstruct a basic ISA representation
                temp_isa_content = self._reconstruct_isa_from_graph(graph)

                # Write to temporary file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.isa', delete=False) as temp_file:
                    temp_file.write(temp_isa_content)
                    temp_isa_path = temp_file.name

                # Add current graph as "current" instruction to the merge
                instruction_dict['current'] = temp_isa_path

                try:
                    result_graph = merge_instructions(instruction_dict)
                    result_graph.infer_uarch_time()
                    return result_graph
                finally:
                    # Clean up temporary file
                    try:
                        os.unlink(temp_isa_path)
                    except:
                        pass
            else:
                # Already a merged graph - can't merge further
                from tkinter import messagebox
                messagebox.showerror(
                    "Cannot Merge",
                    "The currently loaded graph already appears to be merged (contains instruction_enable nodes).\n\n"
                    "Instruction merging can only be applied to single ISA files or empty graphs."
                )
                return None

        # No current graph - just merge the provided files
        result_graph = merge_instructions(instruction_dict)
        result_graph.infer_uarch_time()
        return result_graph

    def _reconstruct_isa_from_graph(self, graph: ResourceGraph) -> str:
        """Reconstruct a basic ISA representation from a graph for merging purposes."""

        # Standard ISA header
        isa_content = """isa_state instr[31:0];
isa_state rf[31:0][4:0];
isa_state imem[31:0][9:0];
isa_state dmem[31:0][9:0];

var rs;
var rt;
var rd;

instr = imem[pc];
assume instr[31:26] == 0;
"""

        # Try to infer instruction type from operation nodes
        operation_nodes = [node for node in graph.nodes.values()
                          if node.data.get('type') == 'operation']

        if operation_nodes:
            # Look for the main operation to determine instruction type
            main_op = None
            for op_node in operation_nodes:
                op_name = op_node.data.get('operator', '').lower()
                if any(keyword in op_name for keyword in ['+', 'add']):
                    main_op = 'add'
                    isa_content += "assume instr[5:0] == 0x20;\n"
                    break
                elif any(keyword in op_name for keyword in ['|', 'or']):
                    main_op = 'or'
                    isa_content += "assume instr[5:0] == 0x25;\n"
                    break

            if not main_op:
                # Default to add if we can't determine
                main_op = 'add'
                isa_content += "assume instr[5:0] == 0x20;\n"
        else:
            # No operation nodes found, default to add
            main_op = 'add'
            isa_content += "assume instr[5:0] == 0x20;\n"

        # Standard instruction decode
        isa_content += """pc = pc + 4;
rs = instr[25:21];
rt = instr[20:16];
rd = instr[15:11];

r1 = rf[rs];
r2 = rf[rt];

"""

        # Add the main operation based on what we found
        if main_op == 'add':
            isa_content += "res = r1 + r2;\n"
        elif main_op == 'or':
            isa_content += "res = r1 | r2;\n"
        else:
            # Fallback
            isa_content += "res = r1 + r2;\n"

        # Standard writeback
        isa_content += "\nrf[rd] = res;\n"

        return isa_content

    def _apply_simple_operation_sharing(self, graph: ResourceGraph, selected_node_ids: List[str] = None) -> ResourceGraph:
        """Apply operation sharing to designer-selected nodes."""
        if not selected_node_ids:
            print("No nodes selected for sharing")
            return None
        success = apply_operation_sharing(graph, selected_node_ids=selected_node_ids, mode=SharingMode.SPATIAL)
        return graph if success else None

    def _change_operation_latency(self, graph: ResourceGraph, selected_nodes: List[str] = None,
                                  latency_type: str = 'fixed', latency_value: int = 1) -> ResourceGraph:
        """Change the latency of an operation.

        Supports both fixed and variable latencies:
        - latency_type = 'fixed': Fixed latency (latency_value cycles)
        - latency_type = 'variable': Variable latency (unknown completion time)

        Automatically handles transitions:
        - Fixed → Variable: Disables fixed latency, enables variable
        - Variable → Fixed: Disables variable latency, sets fixed latency
        - Fixed → Fixed: Changes latency value with proper cleanup

        Args:
            graph: ResourceGraph to transform
            selected_nodes: List of selected node IDs
            latency_type: 'fixed' or 'variable'
            latency_value: Number of cycles (only used when latency_type='fixed')

        Returns:
            Transformed graph or None on failure
        """
        try:
            from opt.temporal.multi_cycle_operations import change_operation_latency, set_operation_variable_latency

            # Find target operation from selected nodes
            target_operation_id = None

            if selected_nodes:
                # Use first selected node that is an operation
                for node_id in selected_nodes:
                    if node_id in graph.nodes:
                        node = graph.nodes[node_id]
                        if node.data.get('type') in ['operation', 'alu_module']:
                            target_operation_id = node_id
                            break

            if not target_operation_id:
                # Fallback: find any operation node
                for node_id, node in graph.nodes.items():
                    if node.data.get('type') in ['operation', 'alu_module']:
                        target_operation_id = node_id
                        break

            if not target_operation_id:
                print("Error: No operation node found (selected or available)")
                return None

            operation = graph.nodes[target_operation_id]
            current_is_variable = operation.variable_latency
            current_latency = operation.latency

            print(f"Changing latency for operation: {target_operation_id}")
            print(f"  Current: {'variable' if current_is_variable else f'{current_latency} cycle(s)'}")
            print(f"  Target: {'variable' if latency_type == 'variable' else f'{latency_value} cycle(s)'}")

            success = False

            if latency_type == 'variable':
                # Setting to variable latency
                if current_is_variable:
                    print("  Operation already has variable latency (no change)")
                    success = True
                else:
                    # Transition: Fixed → Variable
                    print("  Transitioning from fixed to variable latency...")
                    # First disable any existing fixed latency
                    if current_latency > 0:
                        change_operation_latency(graph, target_operation_id, 0)
                    # Then enable variable latency
                    success = set_operation_variable_latency(graph, target_operation_id, enable=True)
            else:
                # Setting to fixed latency
                if current_is_variable:
                    # Transition: Variable → Fixed
                    print("  Transitioning from variable to fixed latency...")
                    # First disable variable latency
                    set_operation_variable_latency(graph, target_operation_id, enable=False)
                    # Then set fixed latency
                    success = change_operation_latency(graph, target_operation_id, latency_value)
                else:
                    # Fixed → Fixed (or combinational → fixed)
                    success = change_operation_latency(graph, target_operation_id, latency_value)

            if success:
                print(f"  ✓ Latency successfully changed")
            else:
                print(f"  ✗ Failed to change latency")

            return graph if success else None

        except ImportError:
            print("Error: multi_cycle_operations module not found")
            return None
        except Exception as e:
            print(f"Change operation latency failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _set_variable_latency(self, graph: ResourceGraph, selected_nodes: List[str] = None,
                              enable: bool = True) -> ResourceGraph:
        """Set an operation to have variable (unknown) latency.

        Args:
            graph: ResourceGraph to transform
            selected_nodes: List of selected node IDs
            enable: If True, enable variable latency. If False, disable it.

        Returns:
            Transformed graph or None on failure
        """
        try:
            from opt.temporal.multi_cycle_operations import set_operation_variable_latency

            # Find target operation from selected nodes
            target_operation_id = None

            if selected_nodes:
                # Use first selected node that is an operation
                for node_id in selected_nodes:
                    if node_id in graph.nodes:
                        node = graph.nodes[node_id]
                        if node.data.get('type') in ['operation', 'alu_module']:
                            target_operation_id = node_id
                            break

            if not target_operation_id:
                # Fallback: find any operation node
                for node_id, node in graph.nodes.items():
                    if node.data.get('type') in ['operation', 'alu_module']:
                        target_operation_id = node_id
                        break

            if not target_operation_id:
                print("Error: No operation node found (selected or available)")
                return None

            print(f"Setting variable latency for operation: {target_operation_id}")
            print(f"  Enable: {enable}")

            # Set variable latency
            success = set_operation_variable_latency(graph, target_operation_id, enable)

            return graph if success else None

        except ImportError:
            print("Error: multi_cycle_operations module not found")
            return None
        except Exception as e:
            print(f"Set variable latency failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _apply_multi_cycle_operations(self, graph: ResourceGraph, selected_nodes: List[str] = None,
                                     latency_cycles: int = 2, operation_type: str = "multi_cycle",
                                     split_nodes: bool = True) -> ResourceGraph:
        """Apply multi-cycle operation transformation.

        Args:
            graph: ResourceGraph to transform
            selected_nodes: List of selected node IDs
            latency_cycles: Number of cycles for the operation
            operation_type: Type of operation
            split_nodes: If True, split into pipeline stages; if False, just set latency attribute

        Returns:
            Transformed graph or None on failure
        """
        try:
            from opt.temporal.multi_cycle_operations import apply_multi_cycle_operations, OperationLatencySpec

            # Find target operation from selected nodes
            target_operation_id = None

            if selected_nodes:
                # Use first selected node that is an operation
                for node_id in selected_nodes:
                    if node_id in graph.nodes:
                        node = graph.nodes[node_id]
                        if node.data.get('type') in ['operation', 'alu_module']:
                            target_operation_id = node_id
                            break

            if not target_operation_id:
                # Fallback: find any operation node
                for node_id, node in graph.nodes.items():
                    if node.data.get('type') in ['operation', 'alu_module']:
                        target_operation_id = node_id
                        break

            if not target_operation_id:
                print("Error: No operation node found (selected or available)")
                return None

            print(f"Applying multi-cycle transformation to: {target_operation_id}")
            print(f"  Split nodes: {split_nodes}")

            # Create latency specification
            spec = OperationLatencySpec(target_operation_id, latency_cycles, operation_type)

            # Apply the transformation
            success = apply_multi_cycle_operations(graph, [spec], split_nodes=split_nodes)

            return graph if success else None

        except ImportError:
            print("Error: multi_cycle_operations module not found")
            return None
        except Exception as e:
            print(f"Multi-cycle operations failed: {e}")
            return None


    def _apply_resource_sharing_or_duplication(self, graph: ResourceGraph, selected_nodes: List[str] = None, mode: str = 'share', sharing_type: str = 'spatial') -> ResourceGraph:
        """Apply resource sharing or duplication optimization.

        Args:
            graph: ResourceGraph to transform
            selected_nodes: List of node IDs to share or duplicate
            mode: 'share' to multiplex operations, 'duplicate' to unroll shared operations
            sharing_type: 'spatial' (mux-based, single cycle) or 'temporal' (counter-based, multi-cycle)

        Returns:
            Modified graph if successful, None otherwise
        """
        if mode == 'duplicate':
            # Unroll shared operations back into parallel operations
            if selected_nodes:
                print("Warning: Node selection is ignored for duplicate mode - all shared operations will be unrolled")

            success = unroll_shared_operations(graph)
            if not success:
                print("No shared operations found to unroll")
                return None
            return graph
        else:  # mode == 'share'
            # Share selected nodes
            if not selected_nodes:
                print("Error: Must select 2 or more nodes of the same type to share")
                return None

            if len(selected_nodes) < 2:
                print(f"Error: Need at least 2 nodes selected for resource sharing (got {len(selected_nodes)})")
                return None

            sharing_mode = SharingMode.TEMPORAL if sharing_type == 'temporal' else SharingMode.SPATIAL
            success = apply_operation_sharing(graph, selected_node_ids=selected_nodes, mode=sharing_mode)
            return graph if success else None

    def _apply_register_file_sharing(self, graph: ResourceGraph, read_ports: int, write_ports: int, read_write_ports: int = 0) -> ResourceGraph:
        """Apply register file port sharing optimization."""
        success = apply_register_file_sharing(graph, read_ports, write_ports, read_write_ports)
        return graph if success else None

    def _apply_memory_externalization(self, graph: ResourceGraph, selected_nodes: List[str] = None, create_read_port: bool = True, create_write_port: bool = True) -> ResourceGraph:
        """Apply memory externalization to convert internal memory to external ports."""
        from opt.memory.memory_externalization import apply_memory_externalization, MemoryExternalizationSpec

        if not selected_nodes or len(selected_nodes) == 0:
            messagebox.showerror("Error", "Please select a memory node to externalize (e.g., dmem, imem, rf)")
            return None

        # Get the first selected node
        memory_node_id = selected_nodes[0]
        memory_node = graph.nodes.get(memory_node_id)

        if not memory_node or not memory_node.data:
            messagebox.showerror("Error", f"Node {memory_node_id} not found")
            return None

        # Get memory name
        memory_name = memory_node.data.get('name', memory_node_id)

        # Check if it's actually a memory
        if not memory_node.data.get('is_memory', False):
            messagebox.showerror("Error", f"Node '{memory_name}' is not a memory. Please select a memory node (dmem, imem, rf, etc.)")
            return None

        # Create specification
        spec = MemoryExternalizationSpec(
            memory_name=memory_name,
            create_read_port=create_read_port,
            create_write_port=create_write_port
        )

        # Apply the optimization
        success = apply_memory_externalization(graph, spec)

        if success:
            messagebox.showinfo("Success", f"Successfully externalized memory '{memory_name}'\n\n"
                              f"Created external ports:\n"
                              f"{'- Read port (input: read_data, output: read_addr)' if create_read_port else ''}\n"
                              f"{'- Write port (outputs: write_addr, write_data, write_enable, and write_be if byte enables exist in graph)' if create_write_port else ''}")
            return graph
        else:
            return None

    def _apply_operation_serialization_or_parallelization(self, graph: ResourceGraph, selected_nodes: List[str] = None, mode: str = 'serialize', granularity_bits: int = 8) -> ResourceGraph:
        """Apply operation serialization or parallelization optimization.

        Args:
            graph: ResourceGraph to transform
            selected_nodes: List of node IDs (used for serialize mode)
            mode: 'serialize' to convert to narrow ops, 'parallelize' to convert to wide ops
            granularity_bits: Bit width for serialization (ignored in parallelize mode)

        Returns:
            Modified graph if successful, None otherwise
        """
        if mode == 'parallelize':
            # Parallelize a specific serialized operation
            if not selected_nodes:
                print("Error: Must select a node from the serialization infrastructure (counter, narrow operation, bit slice, etc.)")
                return None

            # Find which serialization the selected node belongs to
            target_operation_id = None

            for node_id in selected_nodes:
                if node_id in graph.nodes:
                    node = graph.nodes[node_id]
                    node_type = node.data.get('type', '')

                    # Check if this is a serialization-related node
                    if node_type in ['serialization_counter', 'narrow_operation_unit',
                                     'bit_slice_extractor', 'partial_result_storage',
                                     'result_accumulator', 'serialization_completion']:
                        # Extract operation_id from this node
                        operation_id = node.data.get('operation_id')
                        if not operation_id and node_type == 'narrow_operation_unit':
                            # Narrow ops use 'original_operation' field
                            operation_id = node.data.get('original_operation')

                        if operation_id:
                            target_operation_id = operation_id
                            print(f"Detected serialization for operation: {operation_id}")
                            break

            if not target_operation_id:
                print("Error: Selected node is not part of a serialization. Select a counter, narrow operation, bit slice, etc.")
                return None

            # Parallelize just this specific operation
            success = parallelize_serialized_operations(graph, operation_id=target_operation_id, target_granularity=granularity_bits)
            if not success:
                print(f"Failed to parallelize operation: {target_operation_id}")
                return None
            return graph
        else:  # mode == 'serialize'
            # Serialize a wide operation
            try:
                # Find operation to serialize from selected nodes
                target_operation_id = None

                if selected_nodes:
                    # Use first selected node that is an operation
                    for node_id in selected_nodes:
                        if node_id in graph.nodes:
                            node = graph.nodes[node_id]
                            if node.data.get('type') == 'operation':
                                target_operation_id = node_id
                                break

                    if not target_operation_id:
                        print("Error: No operation nodes found in selection")
                        return None  # No operation nodes found in selection
                else:
                    # No nodes selected - find first serializable operation
                    for node_id, node in graph.nodes.items():
                        if node.data.get('type') == 'operation':
                            # Check if it's a serializable operation
                            expr = node.data.get('expression', {})
                            if expr.get('type') == 'binary_op':
                                operator = expr.get('operator')
                                if operator in ['+', '-', '|', '&', '^']:
                                    target_operation_id = node_id
                                    break

                    if not target_operation_id:
                        print("No serializable operations found in graph")
                        return None  # No serializable operations found

                # Create serialization spec
                spec = SerializationSpec(target_operation_id, granularity_bits)
                success = apply_operation_serialization(graph, [spec])
                return graph if success else None
            except Exception as e:
                print(f"Serialization failed: {e}")
                return None

    def _apply_branch_prediction_not_taken(self, graph: ResourceGraph,
                                          pc_node: str = None,
                                          pc_mux: str = None,
                                          not_taken_input: str = None,
                                          taken_input: str = None) -> ResourceGraph:
        """Apply not-taken branch prediction optimization."""
        try:
            success = apply_branch_prediction_not_taken(
                graph,
                pc_node_id=pc_node,
                pc_mux_id=pc_mux,
                not_taken_input_id=not_taken_input,
                taken_input_id=taken_input
            )
            return graph if success else None
        except Exception as e:
            print(f"Branch prediction failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _apply_retiming(self, graph: ResourceGraph, selected_nodes: List[str] = None, direction: str = 'later') -> ResourceGraph:
        """Apply retiming to selected registers in the specified direction."""
        if direction == 'later':
            return self._apply_retiming_forward(graph, selected_nodes)
        elif direction == 'earlier':
            return self._apply_retiming_backward(graph, selected_nodes)
        else:
            print(f"Unknown retiming direction: {direction}")
            return None

    def _apply_retiming_forward(self, graph: ResourceGraph, selected_nodes: List[str] = None) -> ResourceGraph:
        """Apply forward retiming to selected registers."""
        if not selected_nodes:
            print("No nodes selected for retiming")
            return None

        # Filter for only uarch_state nodes
        register_nodes = []
        for node_id in selected_nodes:
            if node_id in graph.nodes:
                node = graph.nodes[node_id]
                if node.is_uarch_state:
                    register_nodes.append(node_id)
                else:
                    print(f"Skipping {node_id} - not a uarch_state register")

        if not register_nodes:
            print("No uarch_state registers selected for retiming")
            return None

        print(f"Retiming {len(register_nodes)} register(s) forward")

        # Check retiming capabilities
        capabilities = get_retimeable_registers(graph)
        for reg_id in register_nodes:
            if reg_id in capabilities:
                if not capabilities[reg_id]['forward']:
                    print(f"Warning: {reg_id} cannot be retimed forward")

        # Apply retiming
        success = apply_retiming_forward(graph, register_nodes)
        return graph if success else None

    def _apply_retiming_backward(self, graph: ResourceGraph, selected_nodes: List[str] = None) -> ResourceGraph:
        """Apply backward retiming to selected registers."""
        if not selected_nodes:
            print("No nodes selected for retiming")
            return None

        # Filter for only uarch_state nodes
        register_nodes = []
        for node_id in selected_nodes:
            if node_id in graph.nodes:
                node = graph.nodes[node_id]
                if node.is_uarch_state:
                    register_nodes.append(node_id)
                else:
                    print(f"Skipping {node_id} - not a uarch_state register")

        if not register_nodes:
            print("No uarch_state registers selected for retiming")
            return None

        print(f"Retiming {len(register_nodes)} register(s) backward")

        # Check retiming capabilities
        capabilities = get_retimeable_registers(graph)
        for reg_id in register_nodes:
            if reg_id in capabilities:
                if not capabilities[reg_id]['backward']:
                    print(f"Warning: {reg_id} cannot be retimed backward")

        # Apply retiming
        success = apply_retiming_backward(graph, register_nodes)
        return graph if success else None

    def _apply_register_renaming(self, graph: ResourceGraph, selected_nodes: List[str] = None, num_physical_regs: int = 64, separate_regfiles: bool = False) -> ResourceGraph:
        """
        Apply register renaming optimization.

        Args:
            graph: ResourceGraph to transform
            selected_nodes: List of node IDs - first should be the resource (e.g., 'rf'),
                           rest are optional index nodes (e.g., 'rs', 'rt', 'rd')
            num_physical_regs: Number of physical registers in the rename table
            separate_regfiles: If True, create separate physical register file; if False, just rename indices

        Returns:
            Modified graph if successful, None otherwise
        """
        if not selected_nodes:
            print("Error: Must select at least the resource node to rename (e.g., 'rf')")
            print("Optionally also select specific index nodes (e.g., 'rs', 'rt', 'rd')")
            return None

        # First selected node should be the architectural state resource
        resource_node_id = selected_nodes[0]

        if resource_node_id not in graph.nodes:
            print(f"Error: Selected resource node '{resource_node_id}' not found in graph")
            return None

        resource_node = graph.nodes[resource_node_id]

        # Verify it's an architectural state node
        if not resource_node.is_arch_state:
            print(f"Error: '{resource_node_id}' is not an architectural state node")
            print("Please select an architectural state resource (like 'rf' for register file)")
            return None

        resource_name = resource_node.data.get('name', resource_node_id)

        # Extract optional index node selections
        target_indices = None
        if len(selected_nodes) > 1:
            # User selected specific index nodes to rename
            index_node_ids = selected_nodes[1:]
            target_indices = []

            for idx_id in index_node_ids:
                if idx_id in graph.nodes:
                    idx_node = graph.nodes[idx_id]
                    # Get the index name from the node
                    idx_name = idx_node.data.get('name', idx_id)
                    target_indices.append(idx_name)
                    print(f"Will rename index: {idx_name}")
                else:
                    print(f"Warning: Index node '{idx_id}' not found, skipping")

            if not target_indices:
                print("Warning: No valid index nodes selected, will rename all indices")
                target_indices = None

        # Create renaming specification
        spec = RegisterRenamingSpec(
            resource_name=resource_name,
            num_physical_regs=num_physical_regs,
            target_indices=target_indices,
            separate_regfiles=separate_regfiles
        )

        print(f"\nApplying register renaming to '{resource_name}':")
        print(f"  Physical registers: {num_physical_regs}")
        print(f"  Mode: {'Separate Physical RF' if separate_regfiles else 'Index Renaming Only'}")
        if target_indices:
            print(f"  Target indices: {', '.join(target_indices)}")
        else:
            print(f"  Target indices: ALL")

        # Apply the optimization
        success = apply_register_renaming(graph, spec)

        if success:
            # Show what was created
            renamed_resources = get_renamed_resources(graph)
            print(f"\n✓ Register renaming applied successfully!")
            print(f"  Renamed resources: {', '.join(renamed_resources)}")

            # Count new components
            renamers = len([n for n in graph.nodes.values() if n.data.get('type') == 'renamer'])
            rename_tables = len([n for n in graph.nodes.values() if n.data.get('type') == 'rename_table'])
            uarch_indices = len([n for n in graph.nodes.values() if n.data.get('type') == 'uarch_index'])
            physical_regfiles = len([n for n in graph.nodes.values() if n.data.get('type') == 'physical_regfile'])

            print(f"  Created components:")
            print(f"    - {renamers} renamer(s)")
            print(f"    - {rename_tables} rename table(s)")
            print(f"    - {uarch_indices} microarchitectural index/indices")
            if separate_regfiles:
                print(f"    - {physical_regfiles} physical register file(s)")
                prf_accesses = len([n for n in graph.nodes.values() if n.data.get('base_resource', '').startswith('prf_')])
                print(f"    - {prf_accesses} PRF access(es)")

            return graph
        else:
            print("\n✗ Register renaming failed or not applicable")
            return None

    def _show_node_selection_help(self, param: Dict):
        """Show a popup with information about which nodes to select."""
        if not self.current_graph:
            messagebox.showinfo("No Graph", "Please load a graph first.")
            return

        # Get optimization context from strategy
        strategy_name = self.strategy_var.get()

        help_window = tk.Toplevel(self.root)
        help_window.title(f"Node Selection Help - {strategy_name}")
        help_window.geometry("600x500")

        # Title
        title_label = ttk.Label(help_window, text=f"Available Nodes for {strategy_name}",
                               font=('TkDefaultFont', 12, 'bold'))
        title_label.pack(pady=10)

        # Instructions based on optimization
        instruction_text = self._get_selection_instructions(strategy_name)
        if instruction_text:
            instr_frame = ttk.LabelFrame(help_window, text="Instructions", padding=10)
            instr_frame.pack(fill=tk.X, padx=10, pady=5)
            instr_label = ttk.Label(instr_frame, text=instruction_text, wraplength=550, justify=tk.LEFT)
            instr_label.pack()

        # List of available nodes by category
        nodes_frame = ttk.LabelFrame(help_window, text="Available Nodes", padding=10)
        nodes_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Create scrollable text widget
        text_widget = tk.Text(nodes_frame, wrap=tk.WORD, height=15, width=70)
        scrollbar = ttk.Scrollbar(nodes_frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)

        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Categorize and display nodes
        self._populate_node_categories(text_widget, strategy_name)

        text_widget.configure(state=tk.DISABLED)

        # Current selection
        if self.selected_nodes:
            selection_frame = ttk.LabelFrame(help_window, text="Currently Selected", padding=10)
            selection_frame.pack(fill=tk.X, padx=10, pady=5)
            selection_text = ", ".join(list(self.selected_nodes)[:10])
            if len(self.selected_nodes) > 10:
                selection_text += f"... ({len(self.selected_nodes)} total)"
            ttk.Label(selection_frame, text=selection_text, wraplength=550).pack()

        # Close button
        ttk.Button(help_window, text="Close", command=help_window.destroy).pack(pady=10)

    def _get_selection_instructions(self, strategy_name: str) -> str:
        """Get specific instructions for node selection based on optimization."""
        instructions = {
            "Out-of-Order Execution": (
                "Select the register file (architectural state resource)\n\n"
                "The OOO optimization needs to know which register file to track:\n"
                "- Issue Queue monitors register reads/writes for dependencies\n"
                "- Reorder Buffer commits results to registers in program order\n\n"
                "Look for nodes named:\n"
                "- 'rf', 'r', 'regs', 'register_file', 'registers', etc.\n"
                "- Should be marked as architectural state\n\n"
                "Your register file can have ANY name - just select the architectural\n"
                "state node that represents your register file!"
            ),
            "Register Renaming": (
                "1. First select the architectural state resource (register file)\n"
                "   - Look for nodes named 'rf', 'r', 'regs', 'register_file', etc.\n"
                "   - These are marked as architectural state (green/blue nodes)\n\n"
                "2. Optionally select specific index nodes to rename\n"
                "   - e.g., 'rs', 'rt', 'rd' for MIPS\n"
                "   - If none selected, ALL indices will be renamed"
            ),
            "Resource Sharing/Duplication": (
                "Select 2 or more nodes of the SAME TYPE to share or duplicate:\n"
                "- Operations (e.g., multiple adders, multipliers)\n"
                "- Resources that can be time-multiplexed\n\n"
                "All selected nodes must have compatible types and bit widths."
            ),
            "Retiming": (
                "Select one or more microarchitectural state registers (gray nodes)\n"
                "- These are uarch_state nodes that act as pipeline registers\n"
                "- You'll move them earlier or later in the pipeline by one cycle"
            ),
            "Operation Serialization/Parallelization": (
                "For SERIALIZE: Select a single wide operation node\n"
                "For PARALLELIZE: Select any node from the serialization infrastructure\n"
                "   - counter, narrow operation, bit slice, etc."
            ),
            "Change Operation Latency": (
                "Select a single operation node whose latency you want to change\n"
                "- Arithmetic operations: +, -, *, /, etc.\n"
                "- Logical operations: &, |, ^, etc.\n"
                "- Comparisons: ==, !=, <, >, etc."
            )
        }
        return instructions.get(strategy_name, "Click on nodes in the graph to select them.\nCtrl+Click to select multiple nodes.")

    def _populate_node_categories(self, text_widget: tk.Text, strategy_name: str):
        """Populate the text widget with categorized nodes."""
        if not self.current_graph:
            return

        # Define useful categories
        arch_state_nodes = []
        uarch_state_nodes = []
        operation_nodes = []
        array_access_nodes = []
        other_nodes = []

        for node_id, node in self.current_graph.nodes.items():
            if node.is_arch_state:
                name = node.data.get('name', node_id) if node.data else node_id
                arch_state_nodes.append((node_id, name))
            elif node.is_uarch_state:
                name = node.data.get('name', node_id) if node.data else node_id
                uarch_state_nodes.append((node_id, name))
            elif node.data and node.data.get('type') == 'operation':
                op = node.data.get('operator', node.data.get('operation', ''))
                operation_nodes.append((node_id, op))
            elif node.data and node.data.get('type') == 'array_access':
                name = node.data.get('name', node_id)
                array_access_nodes.append((node_id, name))
            else:
                other_nodes.append((node_id, node_id))

        # Display categories
        if arch_state_nodes:
            text_widget.insert(tk.END, "📦 ARCHITECTURAL STATE (registers, memory, etc.):\n", "header")
            text_widget.tag_config("header", font=('TkDefaultFont', 10, 'bold'))
            for node_id, name in sorted(arch_state_nodes, key=lambda x: x[1]):
                text_widget.insert(tk.END, f"  • {node_id}")
                if name != node_id:
                    text_widget.insert(tk.END, f" ({name})")
                text_widget.insert(tk.END, "\n")
            text_widget.insert(tk.END, "\n")

        if uarch_state_nodes:
            text_widget.insert(tk.END, "⚙️  MICROARCHITECTURAL STATE (pipeline registers, etc.):\n", "header")
            for node_id, name in sorted(uarch_state_nodes, key=lambda x: x[1]):
                text_widget.insert(tk.END, f"  • {node_id}")
                if name != node_id:
                    text_widget.insert(tk.END, f" ({name})")
                text_widget.insert(tk.END, "\n")
            text_widget.insert(tk.END, "\n")

        if operation_nodes:
            text_widget.insert(tk.END, "🔧 OPERATIONS (arithmetic, logic, etc.):\n", "header")
            for node_id, op in sorted(operation_nodes, key=lambda x: x[1]):
                text_widget.insert(tk.END, f"  • {node_id}: {op}\n")
            text_widget.insert(tk.END, "\n")

        if array_access_nodes:
            text_widget.insert(tk.END, "🔍 ARRAY ACCESSES (rf[rs], mem[addr], etc.):\n", "header")
            for node_id, name in sorted(array_access_nodes, key=lambda x: x[1]):
                text_widget.insert(tk.END, f"  • {node_id}")
                if name != node_id:
                    text_widget.insert(tk.END, f" ({name})")
                text_widget.insert(tk.END, "\n")
            text_widget.insert(tk.END, "\n")

        if other_nodes and len(other_nodes) < 50:  # Only show if not too many
            text_widget.insert(tk.END, "📄 OTHER NODES:\n", "header")
            for node_id, _ in sorted(other_nodes)[:20]:
                text_widget.insert(tk.END, f"  • {node_id}\n")
            if len(other_nodes) > 20:
                text_widget.insert(tk.END, f"  ... and {len(other_nodes) - 20} more\n")

    def _apply_memory_transformation(self, graph: ResourceGraph, memory_name: str = 'umem',
                                    target_width: int = 32, strategy: str = 'set_port_width',
                                    endianness: str = 'little', alignment: str = 'aligned',
                                    selected_ports: List[str] = None, dry_run: bool = False) -> Optional[ResourceGraph]:
        """
        Apply memory access transformation to match memory width constraints.

        Args:
            graph: ResourceGraph to transform
            memory_name: Name of memory to transform (e.g., 'umem', 'dmem', 'imem')
            target_width: Target memory port width in bits
            strategy: Transformation strategy - 'set_port_width', 'serialize_parallelize', 'split_merge', or 'none'
            endianness: Byte order for selection ('little' or 'big')
            alignment: 'aligned' (port_width aligned) or 'unaligned' (cross-word support)
            selected_ports: Optional list of port node IDs for merge operations
            dry_run: If True, preview transformation without applying

        Returns:
            Modified graph if successful, None otherwise
        """
        import copy

        # Map GUI alignment choice to MemoryAccessTransformSpec format
        alignment_mapping = {
            'aligned': 'port_width',
            'unaligned': 'unaligned',
        }
        if alignment not in alignment_mapping:
            raise ValueError(
                f"Unsupported alignment '{alignment}'. Expected one of {list(alignment_mapping.keys())}"
            )
        alignment_spec = alignment_mapping[alignment]

        # Make a copy to preserve the original
        transformed_graph = copy.deepcopy(graph)

        print("\n" + "="*70)
        print("MEMORY ACCESS TRANSFORMATION")
        print("="*70)
        print(f"Memory: {memory_name}")
        print(f"Target width: {target_width} bits")
        print(f"Strategy: {strategy}")
        print(f"Endianness: {endianness}")
        print(f"Alignment: {alignment} ({alignment_spec})")
        print(f"Dry run: {dry_run}")

        # Check if memory exists
        if memory_name not in transformed_graph.nodes:
            print(f"\n❌ Error: Memory '{memory_name}' not found in graph")
            print(f"Available memories: {[n for n in transformed_graph.nodes.keys() if transformed_graph.nodes[n].data.get('type') == 'mem']}")
            return None

        # Strategy: Just set width without transformation
        if strategy == 'none':
            print(f"\n📝 Setting memory width to {target_width} bits (no transformation)")
            if dry_run:
                print(f"\n⚠️  DRY RUN MODE: Width constraint not applied")
                return None
            transformed_graph.set_memory_width(memory_name, target_width)
            print(f"✅ Width constraint set successfully")
            return transformed_graph

        # Strategy: set_port_width - uses MemoryAccessTransform directly
        if strategy == 'set_port_width':
            print(f"\n🔧 Applying set_port_width transformation...")
            try:
                # Get current access width from memory node
                mem_node = transformed_graph.nodes.get(memory_name)
                access_widths = mem_node.data.get('access_widths', [target_width])
                max_width = max(access_widths) if access_widths else target_width
                print(f"   Memory access widths: {access_widths}, max: {max_width}")

                # Determine direction based on current vs target width.
                # For 'set_port_width', `forward` means set the port_width
                # (convert byte-addressed accesses to word-addressed with byte muxes),
                # so when current max access < target port width we should use forward.
                if max_width < target_width:
                    direction = 'forward'   # Add port_width/muxes (e.g., 8->32)
                elif max_width > target_width:
                    direction = 'reverse'   # Remove port_width/muxes (e.g., 32->8)
                else:
                    direction = 'forward'   # Same width: treat as forward (idempotent)
                print(f"   Direction: {direction} (current: {max_width}, target: {target_width})")

                # Create the transform and spec
                transform = MemoryAccessTransform(transformed_graph)
                spec = MemoryAccessTransformSpec(
                    memory=memory_name,
                    strategy='set_port_width',
                    current_width=max_width,
                    target_width=target_width,
                    direction=direction,
                    endianness=endianness,
                    alignment=alignment_spec
                )

                # Apply transformation
                result = transform.apply_transformation(spec, dry_run=dry_run)

                # Display results
                if result.get('transformed'):
                    print(f"\n✅ Transformation successful!")
                    nodes_added = result.get('nodes_added', [])
                    if nodes_added:
                        print(f"\n📦 Nodes added ({len(nodes_added)}):")
                        for node_id in nodes_added[:10]:
                            print(f"   • {node_id}")
                        if len(nodes_added) > 10:
                            print(f"   ... and {len(nodes_added) - 10} more")

                    if dry_run:
                        print(f"\n⚠️  DRY RUN MODE: No changes were actually made")
                        return None
                    else:
                        print(f"\n✅ Graph transformed successfully")
                        return transformed_graph
                else:
                    reason = result.get('reason', 'Unknown reason')
                    print(f"\n⚠️  Transformation not applied: {reason}")
                    return None

            except Exception as e:
                print(f"\n❌ Error during set_port_width transformation: {e}")
                import traceback
                traceback.print_exc()
                return None

        # For other strategies (serialize_parallelize, split_merge), use the optimize_memory_accesses API
        try:
            # Set the target width first
            transformed_graph.set_memory_width(memory_name, target_width)

            # Prepare merge_from parameter for split_merge strategy
            merge_from = None
            if strategy == 'split_merge' and selected_ports:
                # Convert selected node IDs to port names
                merge_from = [node_id for node_id in selected_ports
                            if node_id in transformed_graph.nodes
                            and transformed_graph.nodes[node_id].data.get('is_split_port')]

                if merge_from:
                    print(f"\n📌 Selected ports for merge: {merge_from}")

            # Apply transformation
            print(f"\n🔧 Applying {strategy} transformation...")
            result = transformed_graph.optimize_memory_accesses(
                memory=memory_name,
                strategy=strategy,
                merge_from=merge_from,
                dry_run=dry_run
            )

            # Display results
            if result.get('transformed'):
                print(f"\n✅ Transformation successful!")
                print(f"   Direction: {result.get('direction', 'N/A')}")
                print(f"   Old width: {result.get('old_width', 'N/A')} bits")
                print(f"   New width: {result.get('new_width', 'N/A')} bits")

                if 'cycles_added' in result:
                    print(f"   Cycles added: {result['cycles_added']}")
                if 'cycles_removed' in result:
                    print(f"   Cycles removed: {result['cycles_removed']}")
                if 'ports_required' in result:
                    print(f"   Ports required: {result['ports_required']}")
                if 'ports_merged' in result:
                    print(f"   Ports merged: {result['ports_merged']}")

                if result.get('nodes_added'):
                    print(f"\n📦 Nodes added ({len(result['nodes_added'])}):")
                    for node_id in result['nodes_added'][:5]:
                        print(f"   • {node_id}")
                    if len(result['nodes_added']) > 5:
                        print(f"   ... and {len(result['nodes_added']) - 5} more")

                if result.get('nodes_removed'):
                    print(f"\n🗑️  Nodes removed ({len(result['nodes_removed'])}):")
                    for node_id in result['nodes_removed'][:5]:
                        print(f"   • {node_id}")
                    if len(result['nodes_removed']) > 5:
                        print(f"   ... and {len(result['nodes_removed']) - 5} more")

                if dry_run:
                    print(f"\n⚠️  DRY RUN MODE: No changes were actually made")
                    return None
                else:
                    print(f"\n✅ Graph transformed successfully")
                    return transformed_graph
            else:
                reason = result.get('reason', 'Unknown reason')
                print(f"\n⚠️  Transformation not applied: {reason}")
                return None

        except Exception as e:
            print(f"\n❌ Error during transformation: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _apply_unpipelining(self, graph: ResourceGraph) -> ResourceGraph:
        """
        Apply unpipelining optimization to remove all pipeline components.

        This reverses pipelining optimizations and restores the design to a
        single-cycle implementation.
        """
        from opt.pipeline.unpipelining_optimization import apply_unpipelining_optimization

        # Make a copy to preserve the original
        import copy
        unpipelined_graph = copy.deepcopy(graph)

        print("\n" + "="*70)
        print("APPLYING UNPIPELINING OPTIMIZATION")
        print("="*70)

        # Count pipeline components before
        pipeline_components_before = len([n for n in unpipelined_graph.nodes.values()
                                         if n.data.get('pipeline_component')])

        print(f"\nBefore unpipelining:")
        print(f"  - Total nodes: {len(unpipelined_graph.nodes)}")
        print(f"  - Total edges: {len(unpipelined_graph.edges)}")
        print(f"  - Pipeline components: {pipeline_components_before}")
        print(f"  - Maximum uarch_time: {unpipelined_graph.get_max_uarch_time()}")

        if pipeline_components_before == 0:
            messagebox.showinfo("Info",
                              "No pipeline components found in the design.\n"
                              "The design appears to already be single-cycle.")
            print("\n⚠ No pipeline components to remove")
            return None

        # Apply unpipelining (uses default pipeline_prefix='PIPE')
        success = apply_unpipelining_optimization(unpipelined_graph)

        if success:
            # Count remaining pipeline components
            pipeline_components_after = len([n for n in unpipelined_graph.nodes.values()
                                            if n.data.get('pipeline_component')])

            print(f"\nAfter unpipelining:")
            print(f"  - Total nodes: {len(unpipelined_graph.nodes)}")
            print(f"  - Total edges: {len(unpipelined_graph.edges)}")
            print(f"  - Pipeline components: {pipeline_components_after}")
            print(f"  - Maximum uarch_time: {unpipelined_graph.get_max_uarch_time()}")

            components_removed = pipeline_components_before - pipeline_components_after
            print(f"\n✓ Unpipelining successful!")
            print(f"  - Removed {components_removed} pipeline component(s)")

            if pipeline_components_after > 0:
                print(f"  ⚠ Warning: {pipeline_components_after} pipeline components still present")

            return unpipelined_graph
        else:
            print("\n✗ Unpipelining failed")
            messagebox.showerror("Error", "Unpipelining optimization failed.")
            return None

    def _apply_architectural_retiming(self, graph: ResourceGraph,
                                     target_node: str = None,
                                     strategy: str = 'precomputation',
                                     depth: int = 1) -> ResourceGraph:
        """Apply architectural retiming optimization to a target node."""
        try:
            if not target_node:
                print("No target node selected for architectural retiming")
                return None

            if target_node not in graph.nodes:
                print(f"Target node {target_node} not found in graph")
                return None

            # Show available candidates for reference
            candidates = get_retimeable_nodes(graph)
            if target_node in candidates:
                info = candidates[target_node]
                print(f"Target node info: type={info['type']}, current_time={info['uarch_time']}, max_depth={info['max_depth']}")

            # Apply architectural retiming
            success = apply_architectural_retiming(
                graph,
                target_node_id=target_node,
                strategy=strategy,
                depth=depth
            )
            return graph if success else None

        except Exception as e:
            print(f"Architectural retiming failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _open_result_window(self, optimization_name: str, result_graph: ResourceGraph):
        """Open a new window showing the optimization result."""
        result_window = tk.Toplevel(self.root)
        result_window.title(f"Optimization Result: {optimization_name}")
        result_window.geometry("1000x700")

        # Create result visualizer
        result_visualizer = ResourceGraphVisualizer(result_window)
        result_visualizer.set_graph(result_graph)

        # Add comparison info
        comparison_frame = ttk.Frame(result_window)
        comparison_frame.pack(fill=tk.X, padx=5, pady=5)

        original_info = f"Original: {len(self.current_graph.nodes)} nodes, {len(self.current_graph.edges)} edges"
        result_info = f"Result: {len(result_graph.nodes)} nodes, {len(result_graph.edges)} edges"

        ttk.Label(comparison_frame, text=f"Applied: {optimization_name}").pack(anchor=tk.W)
        ttk.Label(comparison_frame, text=original_info).pack(anchor=tk.W)
        ttk.Label(comparison_frame, text=result_info).pack(anchor=tk.W)


def main():
    """Main entry point for the GUI application."""
    root = tk.Tk()
    app = ResourceGraphVisualizer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
