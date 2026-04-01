#!/bin/bash
# Build RISC-V benchmarks for ISAComp RV64I processors
# This script builds benchmarks from riscv-tests/benchmarks for use with
# both single-cycle and pipelined RV64I processors
#
# Usage: ./build_riscv_benchmarks.sh
#
# Output: Creates .hex and .addrs files for each benchmark in riscv-tests/benchmarks/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARKS_DIR="$SCRIPT_DIR/riscv-tests/benchmarks"
ENV_DIR="$SCRIPT_DIR/riscv-benchmarks-env"
OUTPUT_DIR="$BENCHMARKS_DIR"

# Use 64-bit RISC-V toolchain
GCC=${RISCV_GCC:-riscv64-unknown-elf-gcc}
OBJCOPY=${RISCV_OBJCOPY:-riscv64-unknown-elf-objcopy}
OBJDUMP=${RISCV_OBJDUMP:-riscv64-unknown-elf-objdump}
NM=${RISCV_NM:-riscv64-unknown-elf-nm}

# Check for toolchain
if ! command -v $GCC &> /dev/null; then
    echo "ERROR: RISC-V toolchain not found. Please install riscv64-unknown-elf-gcc"
    echo "On Ubuntu/Debian: sudo apt-get install gcc-riscv64-unknown-elf"
    exit 1
fi

# Benchmarks that work with ISAComp (pure RV64I, no FPU, no multithread)
# Excluded: dhrystone (needs stdio), mm/spmv (need FPU), mt-* (multi-threaded),
# vec-* (vector), pmp (privileged)
BENCHMARKS="median memcpy multiply qsort rsort towers vvadd"

echo "Building RV64I benchmarks for ISAComp..."
echo "Environment: $ENV_DIR"
echo "Output: $OUTPUT_DIR"
echo ""

# Common include paths
INCLUDES="-I$ENV_DIR -I$BENCHMARKS_DIR/common"

# Compile flags for RV64I (no CSR, no multiply extension)
# Use rv64i to ensure pure base integer ISA
CFLAGS="-march=rv64i -mabi=lp64 -mcmodel=medany -O2 -fno-common -fno-builtin"
CFLAGS="$CFLAGS -nostdlib -nostartfiles -static"
CFLAGS="$CFLAGS $INCLUDES"

LDFLAGS="-T$ENV_DIR/link.ld -nostdlib -static"

for bench in $BENCHMARKS; do
    echo -n "Building $bench... "

    BENCH_DIR="$BENCHMARKS_DIR/$bench"

    if [ ! -d "$BENCH_DIR" ]; then
        echo "SKIP (directory not found)"
        continue
    fi

    # Find benchmark source files
    BENCH_SRCS=$(find "$BENCH_DIR" -maxdepth 1 -name "*.c" | sort)

    if [ -z "$BENCH_SRCS" ]; then
        echo "SKIP (no source files)"
        continue
    fi

    # Compile benchmark
    $GCC $CFLAGS $LDFLAGS \
        -o "$OUTPUT_DIR/$bench.elf" \
        "$ENV_DIR/crt.S" \
        "$ENV_DIR/syscalls.c" \
        $BENCH_SRCS \
        2>/dev/null

    if [ $? -ne 0 ]; then
        echo "FAIL (compilation error)"
        continue
    fi

    # Generate hex file (byte per line format for ISAComp)
    # First create raw binary
    $OBJCOPY -O binary "$OUTPUT_DIR/$bench.elf" "$OUTPUT_DIR/$bench.bin"

    # Convert to hex format (one byte per line, for $readmemh)
    xxd -p -c 1 "$OUTPUT_DIR/$bench.bin" > "$OUTPUT_DIR/$bench.hex"

    # Get pass/fail addresses from symbols
    PASS_ADDR=$($NM "$OUTPUT_DIR/$bench.elf" | grep " pass$" | awk '{print $1}')
    FAIL_ADDR=$($NM "$OUTPUT_DIR/$bench.elf" | grep " fail$" | awk '{print $1}')

    if [ -z "$PASS_ADDR" ] || [ -z "$FAIL_ADDR" ]; then
        echo "FAIL (missing pass/fail symbols)"
        rm -f "$OUTPUT_DIR/$bench.elf" "$OUTPUT_DIR/$bench.bin" "$OUTPUT_DIR/$bench.hex"
        continue
    fi

    # Write addresses file
    echo "$PASS_ADDR $FAIL_ADDR" > "$OUTPUT_DIR/$bench.addrs"

    # Generate disassembly for debugging
    $OBJDUMP -d "$OUTPUT_DIR/$bench.elf" > "$OUTPUT_DIR/$bench.dump"

    # Get binary size
    SIZE=$(stat -f%z "$OUTPUT_DIR/$bench.bin" 2>/dev/null || stat -c%s "$OUTPUT_DIR/$bench.bin")

    echo "OK (${SIZE} bytes, pass=0x${PASS_ADDR}, fail=0x${FAIL_ADDR})"

    # Clean up intermediate files
    rm -f "$OUTPUT_DIR/$bench.bin"
done

echo ""
echo "Build complete!"
echo "Hex files are in: $OUTPUT_DIR"
echo ""
echo "To run benchmarks on single-cycle processor:"
echo "  cd examples/verilog/riscv64i_complete && ./run_benchmarks.sh"
echo ""
echo "To run benchmarks on pipelined processor:"
echo "  cd examples/verilog/riscv64i_pipelined_5stage && ./run_benchmarks.sh"
