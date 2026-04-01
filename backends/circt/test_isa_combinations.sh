#!/bin/bash
# Test various ISA instruction combinations

# Change to repository root (two levels up from this script)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
cd "$REPO_ROOT"

echo "Testing CIRCT backend with various ISA combinations..."
echo "=" | sed 's/./=/g' | head -c 60 && echo

test_combination() {
    local name=$1
    shift
    local instrs=("$@")
    
    echo "Testing: $name (${#instrs[@]} instructions)"
    
    # Create temp Python script
    cat > /tmp/test_combo.py << PYEOF
import sys
sys.path.insert(0, '.')
from graph_merger import merge_instructions

instructions = [$(printf "'%s', " "${instrs[@]}")]
isa_files = {instr: f'isa/riscv32/{instr}.isa' for instr in instructions}
graph = merge_instructions(isa_files)
print(f"  Nodes: {len(graph.nodes)}, Edges: {len(graph.edges)}")

mlir = graph.generate_circt('test')
with open('/tmp/test.mlir', 'w') as f:
    f.write(mlir)
print(f"  MLIR: {len(mlir)} bytes")
PYEOF
    
    python3 /tmp/test_combo.py 2>&1 | grep -E "Nodes:|MLIR:"
    
    # Test with circt-opt
    if /tmp/firtool-*/bin/circt-opt /tmp/test.mlir > /dev/null 2>&1; then
        echo "  ✓ CIRCT parsing successful"
    else
        echo "  ✗ CIRCT parsing failed"
    fi
    echo
}

# Test various combinations
test_combination "Arithmetic only" add addi sub
test_combination "Logical operations" and andi or ori xor xori
test_combination "Shifts" sll slli srl srli srai
test_combination "Comparisons" slt slti sltu sltiu
test_combination "Branches" beq bne blt bge bltu bgeu
test_combination "Jumps" jal jalr
test_combination "Loads" lw lh lhu lb lbu
test_combination "Stores" sw sh sb
test_combination "Mixed ALU" add sub and or xor sll srl
test_combination "Complete ALU" add addi sub and andi or ori xor xori sll slli srl srli srai slt slti sltu sltiu

echo "All tests completed!"
