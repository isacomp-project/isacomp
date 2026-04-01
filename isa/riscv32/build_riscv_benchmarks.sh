#!/bin/bash
# Build ISAComp RV32I Benchmarks
# Pure RV32I - no CSR instructions
# Benchmarks start at address 0x0

set -e

RISCV_PREFIX="riscv64-unknown-elf-"
GCC="${RISCV_PREFIX}gcc"
OBJCOPY="${RISCV_PREFIX}objcopy"
OBJDUMP="${RISCV_PREFIX}objdump"
NM="${RISCV_PREFIX}nm"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH_DIR="$SCRIPT_DIR/riscv-tests/benchmarks"
OUTPUT_DIR="$SCRIPT_DIR/riscv-benchmarks"
ISACOMP_ENV="$SCRIPT_DIR/riscv-benchmarks-env"

# Core benchmarks that work with RV32I (no FPU, no vector, no multi-threading)
# Excluded: dhrystone (needs stdio), mm/spmv (need FPU), mt-* (multi-threaded),
# vec-* (vector), pmp (privileged)
BENCHMARKS="median memcpy multiply qsort rsort towers vvadd"

# Option to select specific benchmarks
SELECTED=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --benchmark)
            SELECTED="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --benchmark <name>   Build only specific benchmark"
            echo "  --help               Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ -n "$SELECTED" ]; then
    BENCHMARKS="$SELECTED"
fi

PASS=0
FAIL=0
SKIP=0
FAILED_BENCHMARKS=""

echo "Building ISAComp RV32I Benchmarks..."
echo "======================================"
echo "Pure RV32I - no CSR instructions"

# Check for riscv-tests submodule
if [ ! -d "$BENCH_DIR" ]; then
    echo "ERROR: riscv-tests submodule not initialized"
    echo "Run: git submodule update --init isa/riscv32/riscv-tests"
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

for bench in $BENCHMARKS; do
    BENCH_SRC_DIR="$BENCH_DIR/$bench"

    if [ ! -d "$BENCH_SRC_DIR" ]; then
        echo "  Skipping $bench: No source directory"
        SKIP=$((SKIP + 1))
        continue
    fi

    echo ""
    echo "Building $bench..."

    BENCH_ELF="$OUTPUT_DIR/$bench"
    BENCH_BIN="$OUTPUT_DIR/$bench.bin"
    BENCH_HEX="$OUTPUT_DIR/$bench.hex"
    BENCH_DUMP="$OUTPUT_DIR/$bench.dump"

    # Collect source files
    C_SRCS=""
    ASM_SRCS=""

    for f in "$BENCH_SRC_DIR"/*.c; do
        [ -f "$f" ] && C_SRCS="$C_SRCS $f"
    done

    for f in "$BENCH_SRC_DIR"/*.S; do
        [ -f "$f" ] && ASM_SRCS="$ASM_SRCS $f"
    done

    # Compile with ISAComp environment
    # Pure RV32I without Zicsr extension
    if ! $GCC -march=rv32i -mabi=ilp32 \
         -DPREALLOCATE=0 -mcmodel=medany -static \
         -std=gnu99 -O2 -ffast-math -fno-common \
         -fno-builtin-printf -fno-tree-loop-distribute-patterns \
         -Wno-implicit-int -Wno-implicit-function-declaration \
         -nostdlib -nostartfiles \
         -I"$ISACOMP_ENV" -I"$BENCH_SRC_DIR" \
         -T"$ISACOMP_ENV/link.ld" \
         "$ISACOMP_ENV/crt.S" "$ISACOMP_ENV/syscalls.c" \
         $C_SRCS $ASM_SRCS \
         -o "$BENCH_ELF" 2>&1; then
        echo "    Compilation failed for $bench"
        FAIL=$((FAIL + 1))
        FAILED_BENCHMARKS="$FAILED_BENCHMARKS $bench"
        continue
    fi

    # Extract pass/fail addresses
    PASS_ADDR=$($NM "$BENCH_ELF" | grep " pass$" | awk '{print $1}')
    FAIL_ADDR=$($NM "$BENCH_ELF" | grep " fail$" | awk '{print $1}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "    Warning: Could not find pass/fail symbols"
        PASS_ADDR="0"
        FAIL_ADDR="4"
    fi

    echo "    Compiled: $BENCH_ELF"
    echo "    Pass: 0x$PASS_ADDR, Fail: 0x$FAIL_ADDR"

    # Create binary file
    if ! $OBJCOPY -O binary "$BENCH_ELF" "$BENCH_BIN" 2>/dev/null; then
        echo "    Failed to create binary for $bench"
        FAIL=$((FAIL + 1))
        FAILED_BENCHMARKS="$FAILED_BENCHMARKS $bench"
        continue
    fi

    # Create Verilog-compatible hex file (one byte per line)
    if ! xxd -p -c 1 "$BENCH_BIN" | awk '{printf "%s\n", $0}' > "$BENCH_HEX" 2>/dev/null; then
        echo "    Failed to create hex for $bench"
        FAIL=$((FAIL + 1))
        FAILED_BENCHMARKS="$FAILED_BENCHMARKS $bench"
        continue
    fi

    # Create disassembly
    $OBJDUMP -d "$BENCH_ELF" > "$BENCH_DUMP" 2>/dev/null || true

    # Store addresses in a separate file for easy lookup
    echo "$PASS_ADDR $FAIL_ADDR" > "${BENCH_ELF}.addrs"

    # Get binary size info
    SIZE=$($RISCV_PREFIX"size" "$BENCH_ELF" 2>/dev/null | tail -1 | awk '{print $1}')
    echo "    Size: $SIZE bytes (text)"

    PASS=$((PASS + 1))
done

echo ""
echo "======================================"
echo "Results: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
if [ -n "$FAILED_BENCHMARKS" ]; then
    echo "Failed benchmarks:$FAILED_BENCHMARKS"
fi
echo "======================================"

# Exit with error if any benchmarks failed or none passed
if [ $FAIL -gt 0 ]; then
    echo "FAILED: $FAIL benchmark(s) failed to build"
    exit 1
fi

if [ $PASS -eq 0 ]; then
    echo "FAILED: No benchmarks built successfully (all skipped)"
    exit 1
fi

echo "SUCCESS: All $PASS benchmarks built successfully"
echo "Benchmarks are in: $OUTPUT_DIR/"
exit 0
