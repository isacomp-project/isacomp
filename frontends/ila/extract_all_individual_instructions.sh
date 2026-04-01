#!/bin/bash
# Extract all individual instructions from full ILA models
# Creates separate JSON files for each of the 37 RV32I instructions

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/test_data/riscv/individual"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Extract Individual Instructions${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Create output directory
mkdir -p "${OUTPUT_DIR}"

# Check which model to use (default to Pico)
MODEL="${1:-pico}"
CUSTOM_OUTPUT="${2}"
MODEL_FILE="${SCRIPT_DIR}/test_data/riscv/${MODEL}_full.json"

if [ ! -f "${MODEL_FILE}" ]; then
    echo -e "${RED}✗ Model file not found: ${MODEL_FILE}${NC}"
    echo -e "${YELLOW}Available models:${NC}"
    ls -1 "${SCRIPT_DIR}/test_data/riscv/"*_full.json 2>/dev/null || echo "  None (run ./generate_ila_models.sh first)"
    exit 1
fi

# Use custom output directory if provided, otherwise use model-specific directory
if [ -n "$CUSTOM_OUTPUT" ]; then
    OUTPUT_DIR="$CUSTOM_OUTPUT"
else
    OUTPUT_DIR="${SCRIPT_DIR}/test_data/riscv/${MODEL}"
fi

echo -e "${GREEN}Using model: ${MODEL}${NC}"
echo -e "${BLUE}Source: ${MODEL_FILE}${NC}"
echo -e "${BLUE}Output: ${OUTPUT_DIR}${NC}"
echo ""

# List instructions first
echo -e "${BLUE}Listing available instructions...${NC}"
python3 "${SCRIPT_DIR}/extract_instruction.py" "${MODEL_FILE}" --list
echo ""

# Extract all instructions
echo -e "${BLUE}Extracting all instructions...${NC}"
if python3 "${SCRIPT_DIR}/extract_instruction.py" "${MODEL_FILE}" --all "${OUTPUT_DIR}"; then
    echo ""
    echo -e "${GREEN}✓ Successfully extracted all instructions!${NC}"
    echo ""

    # Show results
    echo -e "${BLUE}Generated files in ${OUTPUT_DIR}:${NC}"
    ls -lh "${OUTPUT_DIR}/"*.json | awk '{printf "  %s %s\n", $9, $5}'

    echo ""
    echo -e "${YELLOW}Total files: $(ls -1 "${OUTPUT_DIR}"/*.json | wc -l)${NC}"
else
    echo -e "${RED}✗ Extraction failed${NC}"
    exit 1
fi
