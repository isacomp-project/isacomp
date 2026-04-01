#!/bin/bash
# Compile CXXRTL simulation
#
# Template: module name is substituted when copied to per-config directories.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODULE_NAME=${MODULE_NAME:-riscv32i_pipelined}
YOSYS_INCLUDE="${YOSYS_INCLUDE:-/usr/share/yosys/include}"

# Only recompile if source is newer
if [ ! -f ${MODULE_NAME}_sim ] || [ ${MODULE_NAME}.cc -nt ${MODULE_NAME}_sim ] || [ ${MODULE_NAME}_tb.cpp -nt ${MODULE_NAME}_sim ]; then
    echo "Compiling CXXRTL simulation..."
    g++ -std=c++14 -O2 -I"$YOSYS_INCLUDE" \
        '-DCXXRTL_ASSERT(x)=(void)(x)' \
        -include ${MODULE_NAME}.cc \
        ${MODULE_NAME}_tb.cpp \
        -o ${MODULE_NAME}_sim
    echo "Compiled: ${MODULE_NAME}_sim"
fi
