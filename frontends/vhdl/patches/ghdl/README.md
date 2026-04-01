# pyGHDL DOM Patches

This directory contains patches for the pyGHDL DOM API to fix issues encountered when parsing complex VHDL designs.

## Target Version

**Target Commit**: `e305f1f54` (GHDL 6.0.0-dev)
**Repository**: https://github.com/ghdl/ghdl

All patches have been verified to apply cleanly to commit `e305f1f54`.

## Patch Files

| Patch | Description |
|-------|-------------|
| `pyghdl-isacomp-all.patch` | Combined patch with all fixes (recommended) |
| `pyghdl-concurrent-nullcheck.patch` | Null checks for Concurrent.py |
| `pyghdl-expression-nullcheck.patch` | Null checks for Expression.py |
| `pyghdl-literal-bitstring.patch` | Bit string literal handling fixes |
| `pyghdl-sequential-fixes.patch` | Sequential statement fixes |
| `pyghdl-translate-variable.patch` | Variable translation fixes |

## pyghdl-dom-nullcheck.patch

**Problem**: pyGHDL DOM throws `AttributeError: 'NoneType' object has no attribute '_parent'` when parsing certain VHDL files with incomplete or complex expression trees.

**Root Cause**: When parsing binary expressions or waveform elements, `GetExpressionFromNode()` can return `None` for null or invalid operands. The code then passes this `None` to pyVHDLModel which tries to set `_parent` attribute, causing a crash.

**Solution**: This patch adds null checks at three critical locations:
1. **Expression.py** (_ParseBinaryExpressionMixin.parse): Check if operands are Null_Iir before parsing, return None if parsing fails
2. **Concurrent.py** (WaveformElement.parse): Return None if expression value is None
3. **Concurrent.py** (ConcurrentSimpleSignalAssignment.parse): Skip None waveform elements
4. **Sequential.py** (SequentialSimpleSignalAssignment.parse): Skip None waveform elements

**Impact**:
- ✅ Allows parsing of Rudi RV32I decode.vhd (165 nodes, 296 edges)
- ✅ Allows parsing of Rudi RV32I program_counter.vhd (37 nodes, 32 edges)
- ✅ Gracefully skips incomplete expressions instead of crashing
- ✅ All other Rudi files continue to parse correctly

**Tested Against**:
- GHDL 5.1.1 + pyTooling 8.5.0
- GHDL 6.0.0-dev + pyTooling 8.7.6

**Status**: Bug exists in both GHDL versions - this is a longstanding pyGHDL DOM issue, not a regression.

## pyghdl-variable-assignment.patch

**Problem**: pyGHDL DOM doesn't support variable assignments in sequential statements, throwing `NotImplementedError`.

**Solution**: Implements `SequentialSimpleVariableAssignment` class to handle variable assignments.

**Impact**:
- ✅ Allows parsing VHDL files with variable assignments
- ✅ Enables support for process-local variables

## pyghdl-case-statement-fix.patch

**Problem**: pyGHDL DOM incorrectly associates case statement alternatives with wrong statements when a case has an 'others' clause. This causes the last regular case choice to get the statements from the 'others' clause instead of its own statements.

**Root Cause**: In `CaseStatement.parse()` at line 299, when processing the 'others' clause, the code calls `Case.parse(alternative, choices, label)` but `alternative` points to the 'others' node, not the previous case's node. The variable `cNode` tracks the correct node but isn't used.

**Example Bug**:
```vhdl
-- Original VHDL:
case res_src is
    when RESULT_ALU => res_bus <= res_alu;           -- Alt 0
    when RESULT_PC_PLUS_4 => res_bus <= res_pc_plus_four; -- Alt 1
    when RESULT_MEMORY => res_bus <= res_memory;     -- Alt 2
    when RESULT_SHIFTER => res_bus <= res_shifter;   -- Alt 3
    when others => res_bus <= res_alu;                -- Alt 4
end case;

-- Buggy parsing result:
-- RESULT_ALU gets: res_bus <= res_alu ✓
-- RESULT_PC_PLUS_4 gets: res_bus <= res_pc_plus_four ✓
-- RESULT_MEMORY gets: res_bus <= res_memory ✓
-- RESULT_SHIFTER gets: res_bus <= res_alu ✗ (should be res_shifter)
```

**Solution**: Change line 299 from:
```python
cases.append(Case.parse(alternative, choices, label))
```
to:
```python
cases.append(Case.parse(cNode, choices, label))
```

**Impact**:
- ✅ Fixes case statement parsing for all cases with 'others' clauses
- ✅ Ensures last regular case gets its correct statements, not 'others' statements
- ✅ Verified fix with Rudi RV32I result_bus_mux.vhd - now correctly generates res_shifter for RESULT_SHIFTER case
- ⚠️ Critical bug - affects VHDL→ResourceGraph→VHDL round-trip fidelity for any design with case statements

**Tested Against**:
- GHDL 6.0.0-dev (commit e305f1f54)
- ISAComp VHDL frontend parsing Rudi RV32I CPU

**Verification**:
Before patch:
```
DEBUG CASE: res_bus <= res_alu [case_choice: RESULT_SHIFTER?]  ✗ Bug!
```

After patch:
```
DEBUG CASE: res_bus <= res_shifter [case_choice: RESULT_SHIFTER?]  ✓ Fixed!
```

## How to Apply

The patches are maintained in this repository. To apply to your local GHDL installation:

```bash
# Clone GHDL and checkout target commit
git clone https://github.com/ghdl/ghdl.git
cd ghdl
git checkout e305f1f54

# Apply the combined patch (recommended)
patch -p1 < /path/to/isacomp/frontends/vhdl/patches/ghdl/pyghdl-isacomp-all.patch

# Or apply individual patches
patch -p1 < /path/to/isacomp/frontends/vhdl/patches/ghdl/pyghdl-concurrent-nullcheck.patch
patch -p1 < /path/to/isacomp/frontends/vhdl/patches/ghdl/pyghdl-expression-nullcheck.patch
patch -p1 < /path/to/isacomp/frontends/vhdl/patches/ghdl/pyghdl-literal-bitstring.patch
patch -p1 < /path/to/isacomp/frontends/vhdl/patches/ghdl/pyghdl-sequential-fixes.patch
patch -p1 < /path/to/isacomp/frontends/vhdl/patches/ghdl/pyghdl-translate-variable.patch

# No rebuild needed - pyGHDL is pure Python and loaded at runtime
# Just restart your Python session to pick up the changes
```

## How to Verify

Test that the patches work:

```bash
cd /path/to/isacomp
python3 -c "
from frontends.vhdl.vhdl_parser_pyghdl import VHDLParserPyGHDL

parser = VHDLParserPyGHDL()

# These files previously failed with NoneType._parent errors
for file in ['decode.vhdl', 'program_counter.vhd', 'result_bus_mux.vhd']:
    path = f'frontends/vhdl/rudi-rv32i/src/cpu/{file}'
    graph = parser.parse_file(path)
    print(f'✓ {file}: {len(graph.nodes)} nodes, {len(graph.edges)} edges')
    parser = VHDLParserPyGHDL()
"
```

Expected output:
```
✓ decode.vhd: 165 nodes, 296 edges
✓ program_counter.vhd: 37 nodes, 32 edges
✓ result_bus_mux.vhd: 7 nodes, 8 edges (with correct edges!)
```

## Upstream Status

These patches should ideally be contributed upstream to the GHDL project. The changes are minimal, well-commented, and follow defensive programming practices by gracefully handling edge cases.

To contribute upstream:
1. Fork https://github.com/ghdl/ghdl
2. Apply these patches
3. Add test cases for the specific VHDL constructs that trigger the bugs
4. Submit pull requests referencing these issues

**pyghdl-case-statement-fix.patch** is particularly important as it's a critical correctness bug affecting all VHDL designs with case statements.

## References

- GHDL Repository: https://github.com/ghdl/ghdl
- pyGHDL Documentation: https://ghdl.github.io/ghdl/pyGHDL/
- ISAComp VHDL Frontend: frontends/vhdl/vhdl_parser_pyghdl.py
