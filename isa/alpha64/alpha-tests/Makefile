# Alpha ISA Test Suite Makefile
# Builds self-checking tests for Alpha processor verification

# Cross-compiler toolchain
CROSS = alpha-linux-gnu-
CC = $(CROSS)gcc-12
AS = $(CROSS)as
LD = $(CROSS)ld
OBJCOPY = $(CROSS)objcopy
OBJDUMP = $(CROSS)objdump

# Directories
ISA_DIR = isa
ENV_DIR = env
BIN_DIR = bin

# Compiler/Assembler flags
ASFLAGS = -I$(ENV_DIR)
LDFLAGS = -T $(ENV_DIR)/link.ld -nostdlib

# Find all test source files
TEST_SRCS = $(wildcard $(ISA_DIR)/*.S)
TEST_ELFS = $(patsubst $(ISA_DIR)/%.S,$(BIN_DIR)/%.elf,$(TEST_SRCS))
TEST_BINS = $(patsubst $(ISA_DIR)/%.S,$(BIN_DIR)/%.bin,$(TEST_SRCS))
TEST_HEXS = $(patsubst $(ISA_DIR)/%.S,$(BIN_DIR)/%.hex,$(TEST_SRCS))
TEST_DUMPS = $(patsubst $(ISA_DIR)/%.S,$(BIN_DIR)/%.dump,$(TEST_SRCS))

# Default target
all: $(BIN_DIR) $(TEST_ELFS) $(TEST_BINS) $(TEST_HEXS) $(TEST_DUMPS)

# Create bin directory
$(BIN_DIR):
	mkdir -p $(BIN_DIR)

# Assemble source to object
$(BIN_DIR)/%.o: $(ISA_DIR)/%.S $(ENV_DIR)/test_macros.h | $(BIN_DIR)
	$(CC) -E -I$(ENV_DIR) $< | $(AS) -o $@

# Link object to ELF
$(BIN_DIR)/%.elf: $(BIN_DIR)/%.o $(ENV_DIR)/link.ld
	$(LD) $(LDFLAGS) $< -o $@

# Convert ELF to raw binary
$(BIN_DIR)/%.bin: $(BIN_DIR)/%.elf
	$(OBJCOPY) -O binary $< $@

# Generate hex file for simulation (32-bit words, little-endian)
$(BIN_DIR)/%.hex: $(BIN_DIR)/%.bin
	od -An -tx4 -v $< | tr -s ' ' '\n' | grep -v '^$$' > $@

# Generate disassembly for debugging
$(BIN_DIR)/%.dump: $(BIN_DIR)/%.elf
	$(OBJDUMP) -d $< > $@

# Clean build artifacts
clean:
	rm -rf $(BIN_DIR)

# List available tests
list:
	@echo "Available tests:"
	@for f in $(TEST_SRCS); do echo "  $$(basename $$f .S)"; done

# Build specific test
test-%: $(BIN_DIR)/%.elf $(BIN_DIR)/%.hex $(BIN_DIR)/%.dump
	@echo "Built test: $*"
	@echo "  ELF:  $(BIN_DIR)/$*.elf"
	@echo "  HEX:  $(BIN_DIR)/$*.hex"
	@echo "  DUMP: $(BIN_DIR)/$*.dump"

# Show test details
show-%: $(BIN_DIR)/%.dump
	@echo "=== $* disassembly ==="
	@cat $(BIN_DIR)/$*.dump

.PHONY: all clean list
.PRECIOUS: $(BIN_DIR)/%.o $(BIN_DIR)/%.elf
