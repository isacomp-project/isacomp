# ISAComp Development Environment
# Based on Ubuntu 24.04 with full support for all ingress/egress formats and verification

FROM ubuntu:24.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /workspace/isacomp

# Update package lists and install base dependencies
RUN apt-get update && apt-get install -y \
    # Build essentials
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    autoconf \
    automake \
    libtool \
    libgmp-dev \
    pkg-config \
    # Version control
    git \
    git-lfs \
    # Python 3 and pip
    python3 \
    python3-pip \
    python3-dev \
    python3-tk \
    # ELF library for VPI modules
    libelf-dev \
    # Verilog simulators
    iverilog \
    verilator \
    gtkwave \
    # VHDL simulator
    ghdl \
    # MIPS cross-compiler (for MIPS32 ISA testing)
    gcc-mips-linux-gnu \
    binutils-mips-linux-gnu \
    # SMT solver (system package)
    z3 \
    # Boost libraries (for ILAng/ILA frontend if building from source)
    libboost-all-dev \
    # Compression utilities
    wget \
    curl \
    unzip \
    bzip2 \
    xz-utils \
    # OCaml and opam for SAIL frontend
    ocaml \
    opam \
    # Additional utilities
    vim \
    nano \
    less \
    tree \
    file \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages for ISAComp
RUN pip3 install --no-cache-dir --break-system-packages \
    z3-solver \
    fusesoc \
    pytest \
    pytest-timeout

# Initialize opam and install SAIL compiler for SAIL frontend
# This is needed for parsing official RISC-V SAIL specifications
RUN opam init --disable-sandboxing --bare -y && \
    opam switch create 4.14.0 && \
    eval $(opam env) && \
    opam install -y sail dune && \
    echo 'eval $(opam env)' >> /root/.bashrc

# Install RISC-V GNU toolchain
# Using pre-built binaries from SiFive/Embecosm for faster build
ARG RISCV_VERSION=2024.02.02
RUN mkdir -p /opt/riscv && \
    cd /tmp && \
    wget -q https://github.com/riscv-collab/riscv-gnu-toolchain/releases/download/${RISCV_VERSION}/riscv64-elf-ubuntu-22.04-gcc-nightly-${RISCV_VERSION}-nightly.tar.gz && \
    tar -xzf riscv64-elf-ubuntu-22.04-gcc-nightly-${RISCV_VERSION}-nightly.tar.gz -C /opt/riscv --strip-components=1 && \
    rm riscv64-elf-ubuntu-22.04-gcc-nightly-${RISCV_VERSION}-nightly.tar.gz

# Add RISC-V toolchain to PATH
ENV PATH="/opt/riscv/bin:${PATH}"

# Note: Additional ISA toolchains (6502, 8086, i486) are not included
# by default to keep the image size reasonable. They can be installed separately if needed:
# - 6502: https://github.com/cc65/cc65
# - x86: https://github.com/lordmilko/i686-elf-tools

# Note: Optional external dependencies (not included by default):
# - ILAng: C++ library for ILA models (requires manual build from https://github.com/PrincetonUniversity/ILAng)
#   The ILA frontend can parse pre-exported JSON without ILAng installed
# - CIRCT: MLIR toolchain (the CIRCT backend generates MLIR, processing CIRCT tools are optional)
#   Install separately from https://github.com/llvm/circt if you want to compile MLIR to Verilog

# Copy the ISAComp source code
COPY . .

# Initialize git submodules (SAIL RISC-V specification)
RUN git submodule update --init --recursive || true

# Build the SAIL extractor (if OCaml dependencies are present)
# This allows extracting instructions from official RISC-V SAIL specs
RUN cd frontends/sail/ocaml_sail_extractor && \
    eval $(opam env) && \
    dune build 2>/dev/null || echo "SAIL extractor build skipped (optional)"

# Set up Python path for ISAComp modules
ENV PYTHONPATH="/workspace/isacomp:${PYTHONPATH}"

# Create output directories
RUN mkdir -p examples/verilog/generated && \
    mkdir -p test_output

# Verify installation by running quick checks
RUN echo "=== ISAComp Environment Setup Complete ===" && \
    echo "Python version:" && python3 --version && \
    echo "Z3 version:" && z3 --version && \
    echo "Icarus Verilog:" && iverilog -v 2>&1 | head -1 && \
    echo "Verilator:" && verilator --version | head -1 && \
    echo "GHDL:" && ghdl --version | head -1 && \
    echo "RISC-V GCC:" && riscv64-unknown-elf-gcc --version | head -1 && \
    echo "MIPS GCC:" && mips-linux-gnu-gcc --version | head -1 && \
    echo "OCaml:" && ocaml --version && \
    eval $(opam env) && echo "SAIL:" && opam list | grep sail || echo "SAIL not installed" && \
    echo "Boost:" && dpkg -l | grep libboost-dev | awk '{print $3}' | head -1

# Default command: show help and available tools
CMD ["/bin/bash", "-c", "echo 'ISAComp Docker Environment' && \
     echo '=========================' && \
     echo '' && \
     echo 'Available commands:' && \
     echo '  ./compile_test.py <isa> <source.S> -o <output.elf>' && \
     echo '  ./run_isa_test.py <isa> <processor_dir> <elf_file>' && \
     echo '  python3 validate_isa_integration.py' && \
     echo '  python3 graph_visualizer.py' && \
     echo '' && \
     echo 'Supported ISAs: riscv32, riscv64, mips32' && \
     echo 'Simulators: iverilog, verilator' && \
     echo 'SMT Solver: z3' && \
     echo '' && \
     echo 'Run /bin/bash for interactive shell' && \
     /bin/bash"]

# Expose no ports by default (this is a development tool, not a server)
# Users can add port mappings if needed for web interfaces

# Health check to verify the environment is ready
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import z3; from core import resource_graph, isa_parser" || exit 1

# Labels for image metadata
LABEL maintainer="ISAComp Development Team"
LABEL description="Complete ISAComp environment with all dependencies for ISA design, verification, and hardware generation"
LABEL version="1.0"
LABEL org.opencontainers.image.source="https://github.com/Jbalkind/isacomp"
