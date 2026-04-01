# ISAComp Docker Environment

This Docker environment provides a complete setup for ISAComp with all dependencies pre-installed for all ingress formats (ISA, SAIL, ILA, Verilog, VHDL), egress formats (Verilog, VHDL, CIRCT, SMT-LIB), and verification backends.

**Note**: ILA frontend can parse pre-exported JSON files. For building ILA models from source, ILAng library must be installed separately. CIRCT backend generates MLIR; CIRCT tools for compiling MLIR are optional.

## Quick Start

### Build the Docker Image

```bash
docker build -t isacomp:latest .
```

Or use the quickstart script: `./docker-quickstart.sh`

This will create an Ubuntu 24.04-based image with:
- Python 3 with z3-solver and FuseSoC
- Verilog simulators: Icarus Verilog and Verilator
- VHDL simulator: GHDL
- Z3 SMT solver
- OCaml with SAIL compiler
- RISC-V GNU toolchain (riscv64-unknown-elf-gcc)
- Boost libraries (for ILAng if building ILA models)
- libelf for ELF parsing

### Run with Docker Compose (Recommended)

```bash
# Start interactive shell
docker-compose run --rm isacomp

# Or use simplified command
docker-compose up -d isacomp
docker-compose exec isacomp /bin/bash
```

### Run Directly with Docker

```bash
# Interactive shell
docker run -it --rm -v $(pwd):/workspace/isacomp isacomp:latest /bin/bash

# Run a specific command
docker run --rm -v $(pwd):/workspace/isacomp isacomp:latest \
    python3 validate_isa_integration.py

# Compile and run a test
docker run --rm -v $(pwd):/workspace/isacomp isacomp:latest \
    ./compile_test.py riscv32 test.S -o test.elf
```

## What's Included

### Ingress Formats (Input)

| Format | Status | Dependencies |
|--------|--------|--------------|
| **ISA files** (.isa) | ✅ Ready | Built-in parser |
| **SAIL** | ✅ Ready | OCaml 4.14, SAIL 0.18+, dune |
| **ILA** (JSON) | ✅ Ready | Built-in parser (parses pre-exported JSON) |
| **ILA** (C++ models) | ⚠️ Optional | Requires ILAng + Boost (manual build) |
| **Verilog/RTL** | ✅ Ready | Built-in parser |
| **VHDL** | ✅ Ready | Built-in frontend |

### Egress Formats (Output)

| Format | Status | Dependencies |
|--------|--------|--------------|
| **Verilog RTL** | ✅ Ready | Icarus Verilog, Verilator |
| **VHDL** | ✅ Ready | GHDL simulator |
| **CIRCT MLIR** | ✅ Ready | Built-in generator (CIRCT tools optional) |
| **SMT-LIB2** | ✅ Ready | Z3 solver |

### Verification Backends

| Backend | Status | Solver |
|---------|--------|--------|
| **SMT-based verification** | ✅ Ready | Z3 (primary) |
| **Equivalence checking** | ✅ Ready | Z3 |
| **Optimization verification** | ✅ Ready | Z3 |
| **Simulation testing** | ✅ Ready | Icarus Verilog, Verilator |

### Cross-Compilers

| ISA | Toolchain | Status |
|-----|-----------|--------|
| **RISC-V 32/64** | riscv64-unknown-elf-gcc | ✅ Included |
| **MIPS 32** | mips-linux-gnu-gcc | ✅ Included |
| **6502** | cc65 | ⚠️ Not included |
| **8086/i486** | i686-elf-gcc | ⚠️ Not included |

Note: RISC-V and MIPS toolchains are included by default. Other toolchains can be installed manually inside the container if needed for your specific ISA.

## Usage Examples

### Example 1: Run the Test Suite

```bash
docker-compose run --rm isacomp python3 -m pytest test/ -v
```

### Example 2: Run a Specific Test

```bash
docker-compose run --rm isacomp python3 -m pytest test/test_roundtrip_riscv32i.py -v
```

### Example 3: Generate Processor from ISA Files

```bash
docker-compose run --rm isacomp /bin/bash

# Inside container:
python3 << 'EOF'
from core.isa_config import get_isa_config
from core.graph_merger import merge_instructions
from backends.verilog.verilog_generator import generate_verilog_with_testbench
from backends.verilog.verilog_testbench_generator import TestbenchConfig

# Load RISC-V32 config
isa = get_isa_config('riscv32')

# Merge instructions from ISA files
instructions = {
    'add': 'isa/riscv32/add.isa',
    'sub': 'isa/riscv32/sub.isa',
    'addi': 'isa/riscv32/addi.isa',
}
graph = merge_instructions(instructions)

# Generate Verilog
files = generate_verilog_with_testbench(graph, "riscv32_alu", "out/riscv32_alu")
print(f"Generated: {files['rtl']}")
EOF
```

### Example 4: Run SMT Verification

```bash
docker-compose run --rm isacomp /bin/bash

# Inside container:
python3 -m pytest test/test_roundtrip_riscv32i.py test/test_alu_spec_parser.py -v
```

### Example 5: Use SAIL Frontend

```bash
docker-compose run --rm isacomp /bin/bash

# Inside container:
cd frontends/sail
eval $(opam env)
./demo_sail_parser.py
```

### Example 6: Interactive Graph Visualizer (with X11 forwarding)

On Linux with X11:

```bash
# Allow Docker to connect to X11
xhost +local:docker

# Run with X11 forwarding
docker run -it --rm \
    -v $(pwd):/workspace/isacomp \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
    isacomp:latest \
    python3 gui/graph_visualizer.py isa/riscv32/add.isa
```

## Development Workflow

### Live Development with Volume Mounting

The docker-compose.yml mounts the current directory, so you can edit files on your host and test them immediately in the container:

```bash
# Terminal 1: Start container
docker-compose up -d isacomp
docker-compose exec isacomp /bin/bash

# Terminal 2: Edit files on host
vim core/resource_graph.py

# Terminal 1: Test changes immediately
python3 test/test_resource_graph.py
```

### Running Tests

```bash
# Run all tests
docker-compose run --rm isacomp python3 -m pytest test/ -v

# Run specific test
docker-compose run --rm isacomp python3 -m pytest test/test_roundtrip_riscv32i.py -v

# Run verification tests (long-running)
docker-compose --profile verification run isacomp-verify
```

## Advanced Configuration

### Custom Toolchain Paths

If you want to use different toolchains, you can mount them:

```yaml
# In docker-compose.yml
volumes:
  - /path/to/custom/toolchain:/opt/custom-toolchain
environment:
  - PATH=/opt/custom-toolchain/bin:$PATH
```

### Build Arguments

Customize the Docker build:

```bash
# Use different RISC-V toolchain version
docker build --build-arg RISCV_VERSION=2024.04.12 -t isacomp:latest .

# Build without SAIL support (faster build)
docker build --target base-only -t isacomp:minimal .
```

### Resource Limits

Adjust resource limits in docker-compose.yml:

```yaml
deploy:
  resources:
    limits:
      cpus: '8'      # Use more CPUs
      memory: 16G    # Use more RAM
```

## Troubleshooting

### Build Fails: "Cannot download RISC-V toolchain"

**Problem**: Network issues or URL changed.

**Solution**:
1. Download the toolchain manually from https://github.com/riscv-collab/riscv-gnu-toolchain/releases
2. Place it in a local directory
3. Modify Dockerfile to COPY the local file instead of wget

### Container Can't Access X11 Display

**Problem**: GUI doesn't work (graph_visualizer).

**Solution**:
```bash
# On Linux
xhost +local:docker
docker run -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix:ro ...

# On macOS
brew install xquartz
# Start XQuartz, then in XQuartz preferences enable "Allow connections from network clients"
xhost + 127.0.0.1
docker run -e DISPLAY=host.docker.internal:0 ...
```

### Out of Memory During Build

**Problem**: Docker build fails with OOM.

**Solution**: Increase Docker memory limit in Docker Desktop settings, or build with `--memory=8g`

### SAIL Extractor Build Fails

**Problem**: OCaml compilation errors.

**Solution**: SAIL extractor is optional. The main isacomp functionality works without it. You can:
1. Use the built-in Python SAIL parser instead (frontends/sail/sail_parser.py)
2. Install SAIL manually: `opam install sail`
3. Skip SAIL if you don't need official RISC-V spec extraction

### Python Import Errors

**Problem**: `ModuleNotFoundError` when running scripts.

**Solution**: Ensure PYTHONPATH is set:
```bash
export PYTHONPATH=/workspace/isacomp:$PYTHONPATH
```

## Performance Tips

1. **Use BuildKit**: Enable Docker BuildKit for faster builds:
   ```bash
   DOCKER_BUILDKIT=1 docker build -t isacomp:latest .
   ```

2. **Layer Caching**: The Dockerfile is structured to maximize layer caching. System packages are installed first, then Python packages, then source code.

3. **Prune Unused Data**: Clean up Docker system periodically:
   ```bash
   docker system prune -a
   ```

4. **Multi-stage Build**: For production, consider creating a multi-stage build that only includes runtime dependencies.

## Image Size

The complete image is approximately **3.0-3.5 GB** and includes:
- Ubuntu 24.04 base (~200 MB)
- Python and libraries (~300 MB)
- OCaml and SAIL (~400 MB)
- RISC-V toolchain (~800 MB)
- MIPS toolchain (~100 MB)
- Simulators (Icarus, Verilator, GHDL) (~600 MB)
- Boost libraries (~200 MB)
- ISAComp source (~200 MB)

To reduce size:
- Remove Verilator (-200 MB)
- Remove GHDL (-100 MB)
- Remove SAIL/OCaml (-400 MB)
- Remove Boost (-200 MB)
- Use alpine base (-150 MB, but requires more work)

## Security Considerations

- The container runs as root by default for development convenience
- For production use, create a non-root user
- Don't expose the container to untrusted networks
- Be cautious when mounting sensitive directories

## Contributing

If you add new dependencies to ISAComp:
1. Update the Dockerfile
2. Rebuild and test: `docker build -t isacomp:latest .`
3. Update this documentation
4. Consider image size impact

## Support

For issues with the Docker environment:
1. Check this documentation
2. Review Docker logs: `docker logs isacomp-dev`
3. File an issue with:
   - Docker version: `docker --version`
   - OS: `uname -a`
   - Build output and error messages

## References

- ISAComp documentation: See README.md and other .md files
- Docker documentation: https://docs.docker.com/
- Docker Compose: https://docs.docker.com/compose/
