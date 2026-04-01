# PDP-11 Test Suite Makefile
# Builds assembly tests into hex files for simulation

PYTHON = python3
ASM = $(PYTHON) pdp11_asm.py
SRCDIR = isa_src
HEXDIR = isa

# Find all assembly source files
SRCS = $(wildcard $(SRCDIR)/*.s)
HEXS = $(patsubst $(SRCDIR)/%.s,$(HEXDIR)/%.hex,$(SRCS))

.PHONY: all clean test

all: $(HEXS)

$(HEXDIR)/%.hex: $(SRCDIR)/%.s pdp11_asm.py | $(HEXDIR)
	@echo "Assembling $<..."
	@$(ASM) $< $@

$(HEXDIR):
	mkdir -p $(HEXDIR)

clean:
	rm -f $(HEXDIR)/*.hex

test: all
	./run_all_tests.sh

# List all tests
list:
	@echo "Available tests:"
	@for f in $(SRCS); do basename $$f .s; done

# Build a specific test
%.hex: $(SRCDIR)/%.s
	$(ASM) $< $(HEXDIR)/$@

.PRECIOUS: $(HEXDIR)/%.hex
