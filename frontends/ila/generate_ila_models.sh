#!/bin/bash
# Generate ILA JSON models from Princeton IMDb RISC-V specifications
# This script builds and runs the ILA exporters for Pico, Piccolo, and Rocket

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ILANG_DIR="${SCRIPT_DIR}/ILAng"
IMDB_DIR="${SCRIPT_DIR}/imdb"
OUTPUT_DIR="${SCRIPT_DIR}/test_data/riscv"
INDIVIDUAL_DIR="${OUTPUT_DIR}/individual"

# ILAng settings
ILANG_INC="${ILANG_DIR}/include"
ILANG_LIB="${ILANG_DIR}/build/src"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ILA Model JSON Generator${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if ILAng is built
if [ ! -f "${ILANG_LIB}/libilang.so" ] && [ ! -f "${ILANG_LIB}/libilang.a" ]; then
    echo -e "${RED}✗ ILAng library not found!${NC}"
    echo -e "${YELLOW}  Please build ILAng first:${NC}"
    echo -e "    cd ${ILANG_DIR}"
    echo -e "    mkdir -p build && cd build"
    echo -e "    cmake .. && make -j\$(nproc)"
    exit 1
fi

echo -e "${GREEN}✓ ILAng library found${NC}"

# Check for z3
if ! command -v z3 &> /dev/null; then
    echo -e "${RED}✗ z3 not found!${NC}"
    echo -e "${YELLOW}  Please install z3: sudo apt-get install z3${NC}"
    exit 1
fi

echo -e "${GREEN}✓ z3 found: $(which z3)${NC}"

# Create output directories
mkdir -p "${OUTPUT_DIR}"
mkdir -p "${INDIVIDUAL_DIR}"

# Function to build and run an exporter
build_and_export() {
    local model_name=$1
    local src_dir=$2
    local export_file=$3
    local output_file=$4

    echo ""
    echo -e "${BLUE}--- Building ${model_name} ---${NC}"

    # Compile the exporter
    if g++ -std=c++17 \
        -I"${src_dir}/include" \
        -I"${ILANG_INC}" \
        -o "${src_dir}/export_${model_name,,}" \
        "${src_dir}/${export_file}" \
        "${src_dir}/src/riscvIla.cc" \
        "${src_dir}/src/helpers.cc" \
        -L"${ILANG_LIB}" \
        -Wl,-rpath,"${ILANG_LIB}" \
        -lilang -lz3 2>&1 | tee "${src_dir}/build.log"; then
        echo -e "${GREEN}✓ ${model_name} compiled successfully${NC}"
    else
        echo -e "${RED}✗ ${model_name} compilation failed${NC}"
        echo -e "${YELLOW}  Check ${src_dir}/build.log for details${NC}"
        return 1
    fi

    # Run the exporter
    echo -e "${BLUE}Exporting ${model_name} to JSON...${NC}"
    if cd "${src_dir}" && "./export_${model_name,,}"; then
        echo -e "${GREEN}✓ ${model_name} exported successfully${NC}"

        # Copy to output directory
        if [ -f "${output_file}" ]; then
            cp "${output_file}" "${OUTPUT_DIR}/"
            echo -e "${GREEN}✓ Copied to ${OUTPUT_DIR}/${output_file}${NC}"
        fi
    else
        echo -e "${RED}✗ ${model_name} export failed${NC}"
        return 1
    fi

    cd "${SCRIPT_DIR}"
}

# Build and export each model
echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Building RISC-V ILA Models${NC}"
echo -e "${BLUE}========================================${NC}"

# Pico
build_and_export \
    "Pico" \
    "${IMDB_DIR}/IMDb_Cores/ILA_Pico/RISC-V-Spec" \
    "export_pico.cc" \
    "pico_full.json"

# Piccolo
build_and_export \
    "Piccolo" \
    "${IMDB_DIR}/IMDb_Cores/ILA_Piccolo" \
    "export_piccolo.cc" \
    "piccolo_full.json"

# Rocket
build_and_export \
    "Rocket" \
    "${IMDB_DIR}/IMDb_Cores/ILA_Rocket" \
    "export_rocket.cc" \
    "rocket_full.json"

# Summary
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Generation Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}Generated models:${NC}"
for file in "${OUTPUT_DIR}"/*.json; do
    if [ -f "$file" ]; then
        size=$(du -h "$file" | cut -f1)
        lines=$(wc -l < "$file")
        echo -e "  • $(basename "$file"): ${size}, ${lines} lines"
    fi
done

echo ""
echo -e "${YELLOW}Note:${NC} These are full models with all 37 RV32I instructions."
echo -e "${YELLOW}      To extract individual instructions, use extract_instruction.py${NC}"
echo ""
