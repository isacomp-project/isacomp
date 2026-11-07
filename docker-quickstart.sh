#!/bin/bash
# ISAComp Docker Quick Start Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored message
print_msg() {
    color=$1
    shift
    echo -e "${color}$@${NC}"
}

print_msg "$BLUE" "========================================"
print_msg "$BLUE" "ISAComp Docker Quick Start"
print_msg "$BLUE" "========================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    print_msg "$RED" "Error: Docker is not installed."
    print_msg "$YELLOW" "Please install Docker from: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is available
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    print_msg "$RED" "Error: Docker Compose is not installed."
    print_msg "$YELLOW" "Please install Docker Compose from: https://docs.docker.com/compose/install/"
    exit 1
fi

# Determine compose command (docker-compose vs docker compose)
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi

print_msg "$GREEN" "✓ Docker is installed"
print_msg "$GREEN" "✓ Docker Compose is available"
echo ""

# Show menu
print_msg "$YELLOW" "What would you like to do?"
echo ""
echo "1) Build the ISAComp Docker image"
echo "2) Start interactive shell"
echo "3) Run validation tests"
echo "4) Compile RISC-V test"
echo "5) Run all tests"
echo "6) Stop all containers"
echo "7) Clean up (remove containers and images)"
echo "0) Exit"
echo ""

read -p "Enter your choice [0-7]: " choice

case $choice in
    1)
        print_msg "$BLUE" "Building ISAComp Docker image..."
        print_msg "$YELLOW" "This may take 10-20 minutes on first build..."
        docker build --cache-from=ghcr.io/isacomp-project/isacomp:build-cache-amd64 --cache-from=ghcr.io/isacomp-project/isacomp:build-cache-arm64 -t isacomp:latest . || {
            print_msg "$RED" "Build failed!"
            exit 1
        }
        print_msg "$GREEN" "✓ Build complete!"
        print_msg "$YELLOW" "Run this script again to start using ISAComp."
        ;;

    2)
        print_msg "$BLUE" "Starting interactive shell..."
        $COMPOSE_CMD run --rm isacomp /bin/bash
        ;;

    3)
        print_msg "$BLUE" "Running validation tests..."
        $COMPOSE_CMD run --rm isacomp python3 validate_isa_integration.py
        ;;

    4)
        print_msg "$BLUE" "Compiling RISC-V test example..."
        $COMPOSE_CMD run --rm isacomp /bin/bash -c "
            echo 'Creating simple test program...'
            cat > /tmp/test_add.S << 'EOF'
.section .text
.globl _start

_start:
    # Test ADD instruction
    addi x1, x0, 5
    addi x2, x0, 3
    add x3, x1, x2

    # x3 should be 8
    addi x4, x0, 8
    beq x3, x4, pass
    j fail

pass:
    j pass

fail:
    j fail
EOF
            echo 'Compiling test...'
            ./compile_test.py riscv32 /tmp/test_add.S -o /tmp/test_add.elf --disassemble
            echo '✓ Compilation complete! ELF file: /tmp/test_add.elf'
        "
        ;;

    5)
        print_msg "$BLUE" "Running all tests..."
        $COMPOSE_CMD run --rm isacomp python3 -m pytest test/ -v
        ;;

    6)
        print_msg "$BLUE" "Stopping all containers..."
        $COMPOSE_CMD down
        print_msg "$GREEN" "✓ All containers stopped"
        ;;

    7)
        print_msg "$RED" "WARNING: This will remove all ISAComp containers and images!"
        read -p "Are you sure? [y/N]: " confirm
        if [[ $confirm =~ ^[Yy]$ ]]; then
            print_msg "$BLUE" "Cleaning up..."
            $COMPOSE_CMD down -v
            docker rmi isacomp:latest || true
            print_msg "$GREEN" "✓ Cleanup complete"
        else
            print_msg "$YELLOW" "Cleanup cancelled"
        fi
        ;;

    0)
        print_msg "$GREEN" "Goodbye!"
        exit 0
        ;;

    *)
        print_msg "$RED" "Invalid choice!"
        exit 1
        ;;
esac

echo ""
print_msg "$GREEN" "Done!"
print_msg "$YELLOW" "For more information, see DOCKER.md"
