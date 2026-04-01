"""
ILAng operation code mappings to ResourceGraph node types.

Based on ILAng source: ilang/ila/ast/expr_op.h
"""

# Expression UIDs (type identifiers)
EXPR_UID_VAR = 1      # Variable
EXPR_UID_CONST = 2    # Constant
EXPR_UID_OP = 3       # Operation

# ILAng operation codes
# NOTE: These MUST match the enum AstUidExprOp in ILAng's ilang/ila/ast/expr_op.h
OP_INVALID = 0       # Invalid
OP_NEG = 1           # Negate
OP_NOT = 2           # Logical NOT
OP_COMPL = 3         # Bitwise complement
OP_AND = 4           # Bitwise AND  ← FIXED: Was 3, now 4
OP_OR = 5            # Bitwise OR   ← FIXED: Was 4, now 5
OP_XOR = 6           # Bitwise XOR  ← FIXED: Was 5, now 6
OP_SHL = 7           # Shift left   ← FIXED: Was 6, now 7
OP_ASHR = 8          # Arithmetic shift right ← FIXED: Was 7, now 8
OP_LSHR = 9          # Logical shift right    ← FIXED: Was 8, now 9
OP_ADD = 10          # Addition
OP_SUB = 11          # Subtraction
OP_MUL = 12          # Multiplication
OP_EQ = 13           # Equal
OP_LT = 14           # Less than    ← FIXED: Was 15, now 14
OP_GT = 15           # Greater than ← FIXED: Was 16, now 15
OP_ULT = 16          # Unsigned less than    ← FIXED: Was 17, now 16
OP_UGT = 17          # Unsigned greater than ← FIXED: Was 19, now 17
OP_LOAD = 18         # Memory load
OP_STORE = 19        # Memory store ← FIXED: Was 20, now 19
OP_CONCAT = 20       # Concatenation ← FIXED: Was 21, now 20
OP_EXTRACT = 21      # Extract bits  ← FIXED: Was 22, now 21
OP_ZEXT = 22         # Zero extend   ← FIXED: Was 23, now 22
OP_SEXT = 23         # Sign extend   ← FIXED: Was 24, now 23
OP_APP_FUNC = 24     # Apply function ← FIXED: Was 31, now 24
OP_IMPLY = 25        # Logical implication ← FIXED: Was 27, now 25
OP_ITE = 26          # If-then-else
OP_DIV = 27          # Divide (added - was missing!)
OP_LROTATE = 28      # Left rotate (added - was missing!)
OP_RROTATE = 29      # Right rotate (added - was missing!)
OP_SREM = 30         # Signed remainder (added - was missing!)
OP_UREM = 31         # Unsigned remainder (added - was missing!)
OP_SMOD = 32         # Signed modular (added - was missing!)

# Map ILAng opcodes to ResourceGraph node types and operators
# Standard format: (node_type, operator_symbol)
OPCODE_TO_NODE_TYPE = {
    OP_ADD: ("operation", "+"),
    OP_SUB: ("operation", "-"),
    OP_MUL: ("operation", "*"),
    OP_DIV: ("operation", "/"),
    OP_AND: ("operation", "&"),
    OP_OR: ("operation", "|"),
    OP_XOR: ("operation", "^"),
    OP_NOT: ("operation", "!"),
    OP_COMPL: ("operation", "~"),
    OP_SHL: ("operation", "<<"),
    OP_ASHR: ("operation", ">>>"),  # Arithmetic shift right (sign-extend)
    OP_LSHR: ("operation", ">>"),   # Logical shift right (zero-fill)
    OP_LROTATE: ("operation", "<<<"),
    OP_RROTATE: ("operation", ">>>"),
    OP_EQ: ("operation", "=="),        # Use ISA type "operation" instead of "comparison"
    OP_LT: ("operation", "<s"),        # Signed less than
    OP_GT: ("operation", ">s"),        # Signed greater than
    OP_ULT: ("operation", "<"),        # Unsigned less than
    OP_UGT: ("operation", ">"),        # Unsigned greater than
    OP_LOAD: ("array_access", None),   # Use ISA type "array_access" instead of "memory_read"
    OP_STORE: ("array_access", None),  # Use ISA type "array_access" instead of "memory_write"
    OP_CONCAT: ("concatenation", None),
    OP_EXTRACT: ("bit_slice", None),
    OP_ZEXT: ("zero_extend", None),
    OP_SEXT: ("sign_extend", None),
    OP_ITE: ("ternary_op", None),      # Use ISA type "ternary_op" instead of "conditional"
    OP_NEG: ("operation", "-"),  # Unary negation
    OP_IMPLY: ("operation", "=>"),
    OP_APP_FUNC: ("function_application", None),
    OP_SREM: ("operation", "%"),  # Signed remainder
    OP_UREM: ("operation", "%"),  # Unsigned remainder
    OP_SMOD: ("operation", "mod"),
}

# Sort UIDs (type identifiers)
SORT_UID_BOOL = 1    # Boolean
SORT_UID_BV = 2      # Bitvector
SORT_UID_MEM = 3     # Memory
SORT_UID_FUNC = 4    # Function

def get_node_type(opcode: int) -> tuple:
    """Get ResourceGraph node type and operator for an ILAng operation code.

    Returns:
        (node_type, operator_symbol) tuple
    """
    return OPCODE_TO_NODE_TYPE.get(opcode, (f"unknown_op_{opcode}", None))

def is_comparison_op(opcode: int) -> bool:
    """Check if operation is a comparison."""
    return opcode in [OP_EQ, OP_LT, OP_GT, OP_ULT, OP_UGT]

def is_memory_op(opcode: int) -> bool:
    """Check if operation is a memory access."""
    return opcode in [OP_LOAD, OP_STORE]

def is_bitwise_op(opcode: int) -> bool:
    """Check if operation is bitwise."""
    return opcode in [OP_AND, OP_OR, OP_XOR, OP_NOT, OP_COMPL]

def is_arithmetic_op(opcode: int) -> bool:
    """Check if operation is arithmetic."""
    return opcode in [OP_ADD, OP_SUB, OP_MUL, OP_NEG]
