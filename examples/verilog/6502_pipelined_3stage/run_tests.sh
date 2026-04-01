#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SIMDIR="$SCRIPT_DIR"
TEST_DIR="$SCRIPT_DIR/../../../isa/6502/6502-tests/bin"
cd "$SIMDIR"
for test in "$TEST_DIR"/*.hex; do
    name=$(basename "${test%.hex}")
    cp "$test" imem.hex
    addrs=$(cat "$TEST_DIR/${name}.addrs")
    pass=$(echo "$addrs" | awk '{print $1}')
    fail=$(echo "$addrs" | awk '{print $2}')
    result=$(timeout 30 vvp ./sim +pass_addr=$pass +fail_addr=$fail 2>&1 | grep -E 'PASSED|FAILED|STALLED')
    echo "$name: $result"
done
