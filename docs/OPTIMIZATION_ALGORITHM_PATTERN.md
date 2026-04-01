# Common Optimization Algorithm Pattern

## Overview

After analyzing the optimization modules in this codebase, a clear architectural pattern emerges across all graph transformations. This document describes the common phases that appear consistently across pipelining, instruction merging, parallel execution, and other optimizations.

## The Universal 7-Phase Pattern

All major optimizations follow this structure:

```
1. ANALYSIS      → Understand what exists
2. PLANNING      → Decide what to change
3. STRUCTURE     → Build new graph components
4. HARDWARE      → Generate actual hardware nodes
5. CONNECTION    → Wire everything together
6. CLEANUP       → Remove superseded elements
7. TIMING        → Update timing information
```

---

## Detailed Phase Breakdown

### Phase 1: ANALYSIS
**Purpose:** Understand the current graph structure and identify opportunities/conflicts

**Common sub-tasks:**
- Dependency analysis (RAW/WAR/WAW hazards)
- Resource access tracking (reads/writes to architectural state)
- Node classification (shared vs instruction-specific)
- Usage pattern analysis (can nodes be shared?)
- Timing analysis (uarch_time distributions)

**Examples across optimizations:**

- **Pipelining** (`pipelining_optimization.py`):
  ```python
  dependency_analysis = DependencyAnalysis(self.graph)
  analysis = dependency_analysis.analyze_dependencies()
  # Finds: resource_reads, resource_writes, potential_hazards
  ```

- **Graph Merging** (`graph_merger.py`):
  ```python
  self._analyze_node_sharing(shared_nodes, instruction_specific_nodes)
  # Determines: which nodes can be shared, which must be duplicated
  ```

- **Parallel Merging** (`parallel_instruction_merging.py`):
  ```python
  dep_analyzer = ParallelDependencyAnalyzer(self.graph_a, self.graph_b)
  self.dependencies = dep_analyzer.analyze()
  # Detects: RAW, WAR, WAW cross-instruction dependencies
  ```

**Key insight:** Analysis is read-only and creates metadata structures, never modifies the graph.

---

### Phase 2: PLANNING/SPECIFICATION
**Purpose:** Create specifications for what transformations to apply

**Common sub-tasks:**
- Create transformation specifications
- Determine cut locations / insertion points
- Plan hardware component IDs and names
- Build transformation schedules

**Examples:**

- **Pipelining**:
  ```python
  stage_spec = PipelineStageSpec(
      cut_location=...,
      stage_name=f"{self.pipeline_prefix}_stage_{i}",
      description=...
  )
  stage_spec.add_hazard_detector(...)
  ```

- **Graph Merging**:
  ```python
  decode_info = InstructionDecodeInfo(name)
  decode_info.add_assume_condition(field, operator, value)
  ```

- **Parallel Merging**:
  ```python
  self.pipeline_assignments[instr_name] = PipelineAssignment(
      instruction_name=instr_name,
      pipeline_id="pipe0",
      can_swap=True
  )
  ```

**Key insight:** Specs are declarative and can be validated before any graph modifications.

---

### Phase 3: STRUCTURE CREATION
**Purpose:** Build the skeleton of new graph components

**Common sub-tasks:**
- Deep copy base graphs
- Create new nodes with proper IDs
- Add instruction prefixes where needed
- Build parallel structures (pipelines, stages)
- Copy/duplicate nodes as specified

**Examples:**

- **Pipelining**:
  ```python
  pipeline_reg = self.pipeline_builder.create_pipeline_register(
      register_id=reg_name,
      stage_name=stage_spec.stage_name
  )
  ```

- **Graph Merging**:
  ```python
  merged_graph = deep_copy_graph(self.graphs[instruction_names[0]])
  # Then add instruction-specific nodes with prefixes
  prefixed_node_id = f"{instr_name}_{node_id}"
  ```

- **Parallel Merging**:
  ```python
  self._create_parallel_structure()
  # Creates separate pipeline lanes with shared arch state
  self._copy_pipeline_nodes(graph_a, instr_a_name, "pipe0")
  ```

**Key insight:** Structure creation establishes the topology without hardware details.

---

### Phase 4: HARDWARE GENERATION
**Purpose:** Create actual hardware components (comparators, muxes, logic gates)

**Common sub-tasks:**
- Create comparators for index matching
- Build multiplexers for resource arbitration
- Generate logic gates (AND, OR)
- Create enable/stall signals
- Build decode logic

**Examples:**

- **Pipelining**:
  ```python
  # Comparator includes stall metadata directly (no intermediate signal node)
  comparator_node = self.hw_factory.comparators.create_index_comparator(
      comp_id=comparator_id,
      left_node=index1_node,
      right_node=index2_node,
      operator='==',
      metadata={'hazard_type': 'RAW', 'resolution': 'stall', 'target_stage': 1}
  )
  ```

- **Graph Merging**:
  ```python
  decode_builder = InstructionDecodeBuilder(graph)
  enable_node = decode_builder.create_instruction_enable_node(...)
  comp_node = decode_builder.create_decode_comparison(...)
  ```

- **Parallel Merging**:
  ```python
  comparator_node = self.hw_factory.comparators.create_index_comparator(...)
  hazard_signal_node = Node(hazard_signal_id, hazard_signal_data)
  ```

**Key insight:** Hardware generation uses builder patterns for consistency and reuse.

---

### Phase 5: CONNECTION/WIRING
**Purpose:** Connect all components with edges to create functional circuits

**Common sub-tasks:**
- Wire inputs to outputs
- Connect mux selects to enable signals
- Link comparators to stall logic
- Insert registers in data paths
- Connect hazard detectors to pipeline controls

**Examples:**

- **Pipelining**:
  ```python
  # Insert pipeline register in edge
  reg_input_edge = Edge(source, pipeline_reg, data={...})
  self.graph.add_edge(reg_input_edge)

  reg_output_edge = Edge(pipeline_reg, target, data={...})
  self.graph.add_edge(reg_output_edge)
  ```

- **Graph Merging**:
  ```python
  # Wire decode comparisons
  decode_builder.wire_decode_logic(comparison_nodes, enable_node)

  # Connect mux to targets
  builder.add_input(source=source_node, select=enable_node, ...)
  builder.connect_output(target_node, 'assignment')
  ```

- **Parallel Merging**:
  ```python
  # Connect comparator to hazard signal
  edge = Edge(comparator_node, hazard_signal_node, data={'type': 'operand'})

  # Connect stall to pipeline enable
  edge = Edge(stall_node, enable_node, data={'type': 'control', 'inverted': True})
  ```

**Key insight:** Connection phase establishes data flow and control dependencies.

---

### Phase 6: CLEANUP
**Purpose:** Remove superseded, orphaned, or dead nodes to maintain graph hygiene

**Common sub-tasks:**
- Remove disconnected nodes
- Delete superseded originals after splitting
- Clean up orphaned instruction-specific nodes
- Remove dead operations with no outputs
- Remove sink nodes with no readers
- Remove bypassed edges

**Examples:**

- **Pipelining**:
  ```python
  # Cleanup happens implicitly when edges are cut and re-routed
  edge.remove_from_nodes()
  if edge.id in self.graph.edges:
      del self.graph.edges[edge.id]
  ```

- **Graph Merging**:
  ```python
  self._cleanup_superseded_nodes(merged_graph, instruction_specific_nodes)
  # Removes:
  # - Disconnected superseded nodes
  # - Orphaned instruction-specific nodes
  # - Dead operations
  # - Sink nodes
  ```

- **All Optimizations**:
  ```python
  optimizer.cleanup_bypassed_edges()  # Standard cleanup pass
  ```

**Key insight:** Cleanup is essential for graph correctness and readability.

---

### Phase 7: TIMING UPDATE
**Purpose:** Re-infer timing information after graph transformations

**Common sub-tasks:**
- Clear downstream timing that's now invalid
- Re-run timing inference algorithms
- Update uarch_time on modified nodes
- Verify critical path is correct

**Examples:**

- **Pipelining**:
  ```python
  # After inserting all stages
  self.graph.infer_uarch_time(force_reinfer=True)
  ```

- **Graph Merging**:
  ```python
  reinfer_timing(graph)  # After loading instruction
  reinfer_timing(merged_graph)  # After merging complete
  ```

- **Parallel Merging**:
  ```python
  self.merged_graph.infer_uarch_time()  # Final timing inference
  ```

**Key insight:** Timing inference is always the last step to ensure correctness.

---

## Common Helper Patterns

### Builder Pattern Usage

All optimizations use builder patterns for hardware generation:

```python
# Hardware builders
self.hw_factory = HardwareBuilderFactory(graph)
comparator = self.hw_factory.comparators.create_index_comparator(...)
# Note: Stall metadata is included directly in comparator, no separate signal node

# Mux builders
builder = MuxBuilder(graph, mux_id, MuxType.PRIORITY)
builder.add_input(source, select, index, metadata)
builder.connect_output(target, edge_type, metadata)

# Pipeline builders
reg = self.pipeline_builder.create_pipeline_register(id, stage_name)

# Decode builders
decode_builder = InstructionDecodeBuilder(graph)
enable = decode_builder.create_instruction_enable_node(...)
```

### Analysis Utilities

All optimizations use analysis utilities:

```python
# Dependency analysis
analyzer = DependencyAnalyzer(graph)
analyzer.analyze()

# Array access analysis
analyzer = ArrayAccessAnalyzer(graph)
access_type = analyzer.classify_access_type(node)

# Timing management
timing_mgr = TimingManager(graph)
critical_path = timing_mgr.get_critical_path()
```

### Graph Utilities

All optimizations use graph utilities:

```python
# Deep copying
new_graph = deep_copy_graph(original_graph)

# Node finding
nodes = find_nodes_by_type(graph, 'operation')
nodes = find_nodes_by_pattern(graph, 'pipe_')

# Reachability
reachable = get_reachable_nodes(start_node, 'forward')
path = find_shortest_path(start_node, end_node)
```

---

## Optimization-Specific Variations

### Pipelining: Iterative Stage Addition

```
1. ANALYSIS:    Find RAW hazards between stages
2. PLANNING:    Create PipelineStageSpec with hazard detectors
3. STRUCTURE:   Create pipeline register
4. HARDWARE:    Create comparators, stall logic, controllers
5. CONNECTION:  Cut edges, insert registers, wire stalls
6. CLEANUP:     Remove cut edges
7. TIMING:      Re-infer after each stage
```

**Unique aspects:**
- Iterative (add one stage at a time)
- Hazard detection between pipeline stages
- Edge cutting and register insertion
- Stall signal propagation

### Graph Merging: Sequential Multi-Instruction

```
1. ANALYSIS:    Analyze node sharing potential
2. PLANNING:    Extract decode conditions from ISA files
3. STRUCTURE:   Deep copy base, add prefixed duplicates
4. HARDWARE:    Create decode logic, muxes, combined enables
5. CONNECTION:  Wire decode comparisons, connect muxes
6. CLEANUP:     Remove superseded, orphaned, dead nodes
7. TIMING:      Re-infer once at end
```

**Unique aspects:**
- Node sharing analysis
- Instruction decode logic
- Priority multiplexers with enables
- Memory write port multiplexing

### Parallel Merging: Dual-Pipeline

```
1. ANALYSIS:    Detect cross-instruction dependencies (RAW/WAR/WAW)
2. PLANNING:    Assign instructions to pipelines
3. STRUCTURE:   Create parallel lanes with shared state
4. HARDWARE:    Create hazard detectors, steering logic
5. CONNECTION:  Wire hazards to stalls, stalls to enables
6. CLEANUP:     (Minimal - new structure, not modifying existing)
7. TIMING:      Re-infer once at end
```

**Unique aspects:**
- Cross-instruction dependency analysis
- Dual pipeline creation
- Instruction steering unit
- Runtime hazard checking (not compile-time)

---

## Design Principles

### 1. Separation of Concerns
- Analysis doesn't modify graphs
- Planning doesn't generate hardware
- Hardware generation doesn't connect
- Cleanup happens after connection

### 2. Builder Pattern Reuse
- Hardware builders provide consistent interfaces
- Reduces code duplication
- Ensures proper node/edge metadata
- Centralizes hardware generation logic

### 3. Defensive Programming
- Validate before modifying
- Check node existence before accessing
- Preserve original edges in metadata
- Track created components to avoid duplicates

### 4. Timing as Last Step
- Always re-infer timing after transformations
- Use `force_reinfer=True` when structure changes
- Clear timing on nodes that move between stages

### 5. Metadata Preservation
- Store `original_type` when replacing edges
- Tag components with `pipeline_component=True`
- Track `instruction` ownership
- Preserve `from_isa_spec` flags

---

## Recommendations for New Optimizations

When implementing a new optimization, follow this template:

```python
class MyOptimization:
    def __init__(self, graph: ResourceGraph):
        self.graph = graph
        self.hw_factory = HardwareBuilderFactory(graph)

    def apply(self) -> bool:
        # PHASE 1: ANALYSIS
        analysis_results = self._analyze()
        if not analysis_results:
            return False

        # PHASE 2: PLANNING
        specs = self._create_specifications(analysis_results)

        # PHASE 3: STRUCTURE
        self._create_structure(specs)

        # PHASE 4: HARDWARE
        components = self._generate_hardware(specs)

        # PHASE 5: CONNECTION
        self._wire_components(components, specs)

        # PHASE 6: CLEANUP
        self._cleanup_graph()

        # PHASE 7: TIMING
        reinfer_timing(self.graph)

        return True
```

This ensures:
- Clear phase separation
- Predictable behavior
- Easy debugging (can inspect after each phase)
- Consistent with existing optimizations

---

## Summary

The 7-phase pattern provides:

1. **Consistency** - All optimizations follow same structure
2. **Composability** - Phases can be mixed/matched
3. **Debuggability** - Clear breakpoints between phases
4. **Maintainability** - New developers know what to expect
5. **Testability** - Each phase can be tested independently

This architectural pattern emerged organically from the needs of graph transformations and has proven robust across pipelining, merging, parallel execution, and other optimizations.
