#!/bin/bash
# Test SMT equivalence for real core ILA extractions vs ISA specs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Which core to test (default: all)
CORE="${1:-all}"

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}SMT VERIFICATION: Real Core ILA Extractions vs ISA${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

test_core() {
    local core=$1
    local core_dir="ila/test_data/riscv/${core}"

    if [ ! -d "$core_dir" ]; then
        echo -e "${YELLOW}⚠ Directory not found: $core_dir${NC}"
        return
    fi

    echo -e "${BLUE}Testing ${core^^} core extractions...${NC}"
    echo ""

    local passed=0
    local failed=0
    local skipped=0

    for isa_file in isa/riscv32/*.isa; do
        basename=$(basename "$isa_file" .isa)
        ila_file="${core_dir}/riscv_${basename}.json"

        printf "  %-8s " "${basename^^}"

        if [ ! -f "$ila_file" ]; then
            echo -e "${YELLOW}⚠ SKIP${NC}"
            ((skipped++))
            continue
        fi

        # Run verification silently, capture result
        if output=$(python3 riscv_smt_equivalence.py "$ila_file" "$isa_file" 2>&1); then
            if echo "$output" | grep -q "SEMANTICALLY EQUIVALENT"; then
                echo -e "${GREEN}✓ PASS${NC}"
                ((passed++))
            else
                echo -e "${RED}✗ FAIL${NC}"
                ((failed++))
            fi
        else
            echo -e "${RED}✗ ERROR${NC}"
            ((failed++))
        fi
    done

    echo ""
    echo -e "${BLUE}${core^^} Results:${NC}"
    echo -e "  ${GREEN}✓ Passed:  $passed${NC}"
    echo -e "  ${RED}✗ Failed:  $failed${NC}"
    echo -e "  ${YELLOW}⚠ Skipped: $skipped${NC}"
    echo ""

    return $failed
}

TOTAL_FAILED=0

if [ "$CORE" = "all" ]; then
    for core in pico piccolo rocket; do
        if ! test_core "$core"; then
            TOTAL_FAILED=$((TOTAL_FAILED + $?))
        fi
        echo ""
    done
else
    test_core "$CORE"
    TOTAL_FAILED=$?
fi

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}OVERALL SUMMARY${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo ""

if [ $TOTAL_FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 SUCCESS! All real core extractions are semantically equivalent to ISA specs!${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠ Some tests failed - check output above${NC}"
    exit 1
fi
