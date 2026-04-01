# ILA Frontend Makefile
#
# Provides convenient commands for testing and using the ILA frontend.

.PHONY: help test test-basic test-realistic clean

help:
	@echo "ILA Frontend for isacomp"
	@echo ""
	@echo "Available targets:"
	@echo "  make test          - Run all ILA frontend tests"
	@echo "  make test-basic    - Run basic parser tests only"
	@echo "  make test-realistic - Run realistic model tests only"
	@echo "  make clean         - Clean temporary files"
	@echo ""
	@echo "To export ILA models from IMDb:"
	@echo "  1. Build ILAng (see ILAng/README.md)"
	@echo "  2. Add JSON export to your model's main.cc:"
	@echo "     IlaSerDesMngr::SerToFile(model.get(), \"output.json\");"
	@echo "  3. Build and run your model"
	@echo "  4. Parse: python3 -c 'from resource_graph import ResourceGraph; g = ResourceGraph.from_ila_json_file(\"output.json\")'"
	@echo ""

test:
	@echo "Running all ILA frontend tests..."
	@./run_tests.sh

test-basic:
	@echo "Running basic ILA parser tests..."
	@python3 test_ila_parser.py

test-realistic:
	@echo "Running realistic ILA model tests..."
	@python3 test_ila_realistic.py

clean:
	@echo "Cleaning temporary files..."
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.pyo" -delete
	@rm -f /tmp/test_ila_model.json
	@echo "Done."
