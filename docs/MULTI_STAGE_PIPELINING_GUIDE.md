# Multi-Stage Manual Pipelining - GUI Guide

## Overview

The **Multi-Stage Manual Pipelining** optimization allows you to build complex multi-stage pipelines through an interactive side panel interface. Unlike the single-stage "Manual Pipelining" which requires repeated applications, this optimization provides a unified interface where you can select edges for all pipeline **cuts** (between stages) and apply them all at once with automatic hazard detection.

**Key Concept**: For N stages, you need N-1 pipeline cuts. For example:
- 2 stages → 1 cut
- 3 stages → 2 cuts
- 5 stages → 4 cuts

## Key Features

✅ **Non-Modal Side Panel**: X-forwarding friendly interface that stays open while you work
✅ **Visual Edge Selection**: Click edges in the graph to assign them to stages
✅ **Color-Coded Feedback**: Each stage's edges are highlighted in a different color
✅ **Automatic Hazard Detection**: Each stage gets hazard detection hardware with comparators, signals, and stalls
✅ **Named Pipeline Stages**: Give meaningful names to each stage (fetch, decode, execute, etc.)
✅ **Single Apply Button**: Select edges for all stages, then apply everything at once

## Quick Start

### Step 1: Launch GUI and Load ISA

```bash
python3 graph_visualizer.py
```

Load an ISA file (e.g., `isa/mips32/add.isa`)

### Step 2: Select Multi-Stage Manual Pipelining

1. In the "Optimization Strategies" panel on the right
2. Click the "Strategy:" dropdown
3. Select **"Multi-Stage Manual Pipelining"**

### Step 3: Configure Pipeline

Set the parameters:

- **num_stages**: Number of pipeline stages to create (e.g., `3`)
- **stage_names**: Comma-separated stage names (e.g., `fetch,decode,execute`)
- **selected_edges**: Leave this empty (will be selected in the panel)

### Step 4: Open the Multi-Stage Panel

Click **"Apply Optimization"**

This opens a non-modal side panel titled "Multi-Stage Pipeline Builder" showing:
- Header with stage count and number of cuts needed
- All your pipeline **cuts** listed (N-1 cuts for N stages)
- Each cut shows which two stages it's between
- Edge count for each cut (initially "0 edges selected")
- "Select Edges for This Cut" button for each cut
- "Apply All Stages" button at the bottom
- Scrollable list if you have many stages

### Step 5: Select Edges for Each Cut

For each cut (between stages):

1. **Click "Select Edges for This Cut"** button in the panel
   - The cut frame will be highlighted
   - Status bar shows which cut is active (e.g., "between 'fetch' and 'decode'")

2. **Click edges in the main graph**
   - Click any edge to add it to the current cut
   - Edges will be highlighted in a color specific to that cut
   - Edge count updates automatically
   - Ctrl+Click to toggle edge selection on/off

3. **Use "Clear Selection"** to reset edges for a cut if needed

4. **Repeat** for all cuts

### Step 6: Apply All Stages

When all cuts have edges selected:

1. Click **"Apply All Stages"**
2. The system will:
   - Validate all selections
   - Apply each pipeline cut sequentially
   - Add hazard detection after each cut
   - Open a new window with the pipelined result

You'll see a success dialog:
```
Multi-stage pipelining complete!

Created 3 stages with 2 cuts
Stages: fetch, decode, execute

Pipeline depth: 3 cycles
Total nodes: 45
```

## Example Workflow

### Creating a 3-Stage MIPS32 ADD Pipeline

**Goal**: Create fetch → decode → execute pipeline (3 stages = 2 cuts)

#### Initial Setup

```
1. Load isa/mips32/add.isa
2. Select "Multi-Stage Manual Pipelining"
3. Set num_stages = 3
4. Set stage_names = "fetch,decode,execute"
5. Click "Apply Optimization" to open the panel
6. Panel shows: "Need 2 pipeline cuts between stages"
```

#### Cut 1: Between Fetch and Decode

**What to cut**: Separate instruction fetch from decode

```
1. In the panel, click "Select Edges for This Cut" for Cut 1 (fetch → decode)
2. In the main graph, click these edges:
   - imem[pc] → instr (instruction memory read)
   - pc_rd → (pc + 4) (PC calculation)
3. Edges turn red (Cut 1 color)
4. Panel shows "2 edges selected" for this cut
```

#### Cut 2: Between Decode and Execute

**What to cut**: Separate decode from execute

```
1. In the panel, click "Select Edges for This Cut" for Cut 2 (decode → execute)
2. In the main graph, click these edges:
   - instr → rs, rt, rd (instruction decode)
   - rf[rs] → r1 (register read)
   - rf[rt] → r2 (register read)
3. Edges turn teal (Cut 2 color)
4. Panel shows "3 edges selected" for this cut
```

#### Apply All Cuts

```
1. Click "Apply All Stages" in the panel
2. System applies:
   - Cut 1: Inserts pipeline registers named "decode_reg"
   - Adds hazard detection for decode stage
   - Cut 2: Inserts pipeline registers named "execute_reg"
   - Adds hazard detection for execute stage
3. Success dialog appears
4. New window opens with the complete 3-stage pipeline
```

**Result**: 3-stage pipeline (fetch → decode → execute) with 2 cuts and full hazard detection

## Visual Feedback

The multi-stage panel provides rich visual feedback:

### Edge Colors

Each cut gets a unique color for its selected edges:
- **Cut 1**: Red (#FF6B6B)
- **Cut 2**: Teal (#4ECDC4)
- **Cut 3**: Blue (#45B7D1)
- **Cut 4**: Light Orange (#FFA07A)
- **Cut 5**: Mint (#98D8C8)
- **Cut 6**: Pink (#FFB6C1)
- **Cut 7**: Sky Blue (#87CEEB)
- **Cut 8**: Plum (#DDA0DD)

Colors repeat for 9+ cuts.

### Cut Highlighting

When you click "Select Edges for This Cut":
- The cut frame becomes **raised with a 3px border**
- Other cuts remain flat with 2px borders
- Status bar shows which stages the cut is between

### Edge Count Updates

The edge count label updates in real-time:
- "0 edges selected" initially
- "1 edge selected" after first click
- "5 edges selected" etc.

## Understanding the Results

### Pipeline Registers

Each stage insertion creates pipeline registers:

```
Stage 1 "fetch":
  - imem[pc]_fetch_reg
  - pc_rd_fetch_reg

Stage 2 "decode":
  - instr_decode_reg
  - rf[rs]_decode_reg
  - rf[rt]_decode_reg

Stage 3 "execute":
  - r1_execute_reg
  - r2_execute_reg
  - res_execute_reg
```

### Hazard Detection Hardware

For each stage (except the last), hardware is automatically generated:

**Comparators**:
- Check if register indices match (e.g., `rd == rs`)

**Hazard Signals**:
- Generated when hazards are detected

**Stall Signals**:
- Created from hazard signals

**Stall Controllers**:
- Connect all stall signals for the stage

### Example Hazard Hardware for "fetch" Stage:

```
HAZARD_fetch_PIPE_stage_0_hazard_0_cmp
  └─> HAZARD_fetch_PIPE_stage_0_hazard_0_signal
      └─> HAZARD_fetch_PIPE_stage_0_hazard_0_stall
          └─> HAZARD_fetch_PIPE_stage_0_stall_ctrl
```

## Advanced Usage

### Custom Stage Names

You can use any stage names you want:

```
num_stages = 5
stage_names = "IF,ID,EX,MEM,WB"
```

Or:

```
num_stages = 4
stage_names = "frontend,issue,execute,commit"
```

### Fewer Stage Names Than Stages

If you provide fewer names than stages, defaults are used:

```
num_stages = 5
stage_names = "fetch,decode"

Results in:
  - Stage 1: "fetch"
  - Stage 2: "decode"
  - Stage 3: "stage_3"
  - Stage 4: "stage_4"
  - Stage 5: "stage_5"
```

### Resuming After Interruption

The optimization tracks progress automatically. If you:
- Close a result window
- Load the partially-pipelined graph
- Apply Multi-Stage Manual Pipelining again

It will resume from the next stage!

### Combining with Other Optimizations

You can apply other optimizations to the pipelined result:

```
1. Complete multi-stage pipelining
2. Apply "Resource Sharing" to share ALUs between stages
3. Apply "Multi-Cycle Operations" to specific operations
4. Apply "Retiming" to adjust register placement
```

## Tips and Best Practices

### 1. Plan Your Stages First

Before starting, decide:
- How many stages you want
- What computation happens in each stage
- Where the natural boundaries are

### 2. Start with Key Boundaries

For a typical RISC pipeline:
```
Stage 1 (Fetch):      Instruction memory access
Stage 2 (Decode):     Instruction decode, register read
Stage 3 (Execute):    ALU operations
Stage 4 (Memory):     Data memory access
Stage 5 (Writeback):  Register write
```

### 3. Select Complete Cuts

Make sure all data dependencies cross your selected edges:
- If validation fails, you'll get an error
- Select additional edges that cross the boundary
- Use "Show Timing" checkbox to visualize timing layers

### 4. Use Meaningful Names

Good names make the pipeline easier to understand:

✅ Good: `fetch,decode,execute,memory,writeback`
✅ Good: `IF,ID,EX,MEM,WB`
❌ Bad: `s1,s2,s3,s4,s5`

### 5. Check Hazard Detection

After each stage, check the console output:

```
Adding hazard detection for stage fetch...
  Found 2 potential hazards
  Added 2 hazard detectors with hardware generation
```

### 6. Visualize Results

After completion:
- Use "Pipeline Layout" to see stages clearly
- Enable "Show Timing" to see cycle numbers
- Click on hazard detector nodes to inspect them

## Troubleshooting

### Error: "The following cuts have no edges selected"

**Cause**: You clicked "Apply All Stages" but some cuts are empty

**Solution**:
1. Check which cuts are listed in the error dialog
2. Click "Select Edges for This Cut" for those cuts
3. Select edges in the graph
4. Click "Apply All Stages" again

### Error: "Selected edges do not form a valid pipeline cut"

**Cause**: One cut's edge selection doesn't cleanly separate the pipeline

**Solution**:
1. Look at the console output - it shows which cut failed
2. Console lists edges that also need to be cut
3. Click "Select Edges for This Cut" for that cut
4. Add those additional edges
5. Click "Apply All Stages" again

### No Hazards Detected

**Cause**: The selected edges don't create RAW dependencies

**Why**: This is normal for some stages (like final writeback)

**Action**: No action needed - pipeline still works correctly

### Edges Not Highlighting

**Cause**: You haven't activated a cut for selection

**Solution**:
1. Click "Select Edges for This Cut" for the cut you want
2. The cut frame will be highlighted
3. Now edges will be colored when you click them

### Can't See All Cuts in Panel

**Cause**: You have many stages and the panel isn't scrolling

**Solution**:
1. The panel should be scrollable - use mousewheel to scroll
2. Panel height is fixed at 400px with scrollbar
3. Window can be resized if needed (450x700 default)

### Panel Closed Accidentally

**Cause**: Closed the panel window before applying

**Solution**:
1. Edge selections were cleared
2. Click "Apply Optimization" again to reopen the panel
3. Reselect edges for all stages

## Comparison with Single-Stage Manual Pipelining

| Feature | Multi-Stage | Single-Stage |
|---------|------------|--------------|
| **Interface** | ✅ Non-modal side panel | ❌ Select-apply-repeat |
| **Progress Tracking** | ✅ Visual panel with all stages | ❌ Manual |
| **Edge Selection** | ✅ Click in graph, color-coded | ✅ Click in graph, purple |
| **Stage Names** | ✅ Named per-stage | ✅ Global name |
| **Hazard Detection** | ✅ Automatic after each stage | ❌ Manual |
| **Application** | ✅ All at once | ❌ One at a time |
| **X-Forwarding** | ✅ Non-modal, works well | ⚠️ Works fine |
| **Use Case** | Building complete pipelines | Adding one stage at a time |

**When to use Multi-Stage**:
- Creating a complete pipeline (2+ stages)
- Want to see all stages before applying
- Want automatic hazard detection
- Building a standard RISC pipeline
- Working over X-forwarding/SSH

**When to use Single-Stage**:
- Adding just one pipeline stage
- Doing experimental pipelining
- Want incremental results after each stage
- Iterating on pipeline structure

## Console Output Example

```
================================================================================
APPLYING MULTI-STAGE PIPELINE
================================================================================

======================================================================
Adding pipeline stage 1/3: fetch
======================================================================
Selected 2 edges for this stage
Pipeline cut validation: checking 2 selected edges
...
Manual pipelining: inserted 2 pipeline registers
Re-inferring timing after manual pipelining...

Adding hazard detection for stage fetch...
  Found 2 potential hazards
  Added 2 hazard detectors with hardware generation

======================================================================
Adding pipeline stage 2/3: decode
======================================================================
Selected 3 edges for this stage
...

======================================================================
Adding pipeline stage 3/3: execute
======================================================================
Selected 2 edges for this stage
...

================================================================================
MULTI-STAGE PIPELINING COMPLETE
================================================================================
Created 3 pipeline stages:
  Stage 1: fetch (2 pipeline registers)
  Stage 2: decode (3 pipeline registers)
  Stage 3: execute (2 pipeline registers)

Total nodes: 45
Pipeline depth: 3 cycles
================================================================================
```

## Summary

Multi-Stage Manual Pipelining makes it easy to:

✅ Build complex multi-stage pipelines with a unified interface
✅ See all pipeline stages at once in a non-modal side panel
✅ Select edges visually with color-coded feedback per stage
✅ Get automatic hazard detection with real hardware
✅ Apply all stages at once with validation
✅ Use meaningful stage names
✅ Work efficiently over X-forwarding/SSH

The feature combines the flexibility of manual edge selection with the convenience of a visual interface and automatic hazard generation, all while remaining X-forwarding friendly with its non-modal design.

## Next Steps

After creating your pipeline:

1. **Analyze Dependencies**: Click "Analyze Dependencies" to see inter-stage hazards
2. **Save**: Save your pipelined graph for future use
3. **Optimize Further**: Apply other optimizations as needed
4. **Generate Verilog**: Use the graph to generate hardware (if available)

Happy pipelining! 🚀
