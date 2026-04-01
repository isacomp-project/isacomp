.PHONY: build clean test extract-riscv help

# Default target
all: build

help:
	@echo "SAIL to ResourceGraph Extractor - Build Targets"
	@echo ""
	@echo "  make build         - Build the OCaml extractor"
	@echo "  make clean         - Clean build artifacts"
	@echo "  make extract-riscv - Extract all RISC-V instructions"
	@echo "  make test          - Run quick test extraction"
	@echo "  make deps          - Install OCaml dependencies"
	@echo ""

# Build the extractor
build:
	@echo "Building SAIL extractor..."
	dune build
	@echo "✓ Built: _build/default/sail_to_rgraph.exe"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	dune clean
	@echo "✓ Clean complete"

# Extract all RISC-V instructions from sail-riscv
extract-riscv: build
	@echo "Extracting RISC-V instructions from sail-riscv..."
	@echo "This may take 1-2 minutes..."
	dune exec ./sail_to_rgraph.exe ../sail-riscv/model/riscv.sail_project /tmp/riscv_instructions.json --per-instruction
	@echo ""
	@echo "✓ Extraction complete!"
	@echo "  Output: /tmp/riscv_instructions.json"
	@echo ""
	@echo "To use in Python:"
	@echo "  python3 ../sail_loader.py --list"

# Quick test on execute function only
test: build
	@echo "Running quick test extraction (execute function only)..."
	dune exec ./sail_to_rgraph.exe ../sail-riscv/model/riscv.sail_project /tmp/test_execute.json --function execute --per-instruction
	@echo ""
	@echo "✓ Test complete!"
	@echo "  Output: /tmp/test_execute.json"

# Install dependencies (requires opam)
deps:
	@echo "Installing OCaml dependencies via opam..."
	@echo "This requires opam to be installed and initialized."
	@echo ""
	opam install -y sail dune
	@echo ""
	@echo "✓ Dependencies installed"
	@echo ""
	@echo "Note: z3 SMT solver is also required (system package)"
	@echo "  Ubuntu/Debian: sudo apt-get install z3"
	@echo "  macOS: brew install z3"

# Check if dependencies are installed
check-deps:
	@echo "Checking dependencies..."
	@which opam > /dev/null || (echo "✗ opam not found" && exit 1)
	@echo "✓ opam found"
	@which dune > /dev/null || (echo "✗ dune not found (run 'make deps')" && exit 1)
	@echo "✓ dune found"
	@opam list sail | grep -q sail || (echo "✗ sail not found (run 'make deps')" && exit 1)
	@echo "✓ sail found"
	@which z3 > /dev/null || echo "⚠ z3 not found (SAIL type checking may fail)"
	@echo "✓ All dependencies OK"
