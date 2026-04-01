# Patches for isacomp

This directory contains patches for bugs discovered and fixed in isacomp and related tools.

## 001-fix-ilang-opcode-mapping.patch

**Bug**: Incorrect ILAng operation code mapping in `ila/ila_opcodes.py`

**Impact**: All bitwise operations (AND, OR, XOR) and many other operations were being incorrectly parsed from ILA JSON files, causing:
- AND operations interpreted as OR
- OR operations interpreted as XOR
- XOR operations interpreted as shift_left
- And many other off-by-one mapping errors

**Root Cause**: The opcode mapping was offset by 1 from ILAng's actual enum values. We skipped `kInvalid = 0` but started our mapping at the wrong position.

**Discovery**: Found through SMT-based equivalence checking between ILA models and ISA specifications. The checker correctly identified semantic differences.

**Fix**: Corrected all opcode values to match ILAng's `enum AstUidExprOp` in `ilang/ila/ast/expr_op.h`:
- OP_AND: 3 → 4
- OP_OR: 4 → 5
- OP_XOR: 5 → 6
- OP_SHL: 6 → 7
- And all subsequent opcodes shifted accordingly
- Added missing opcodes: DIV, LROTATE, RROTATE, SREM, UREM, SMOD

**Verification**: After fix, bitwise operations correctly parse:
```
✓ AND: bitwise_and (was bitwise_or)
✓ OR:  bitwise_or  (was bitwise_xor)
✓ XOR: bitwise_xor (was shift_left)
```

**Date**: 2025-10-26
**Detected by**: SMT equivalence checker
**Fixed by**: Claude Code
