#!/usr/bin/env python3
"""Convert boot.bin into hex files for $readmemh loading by generated RTL.

The ISAComp Verilog generator creates an initial block that loads memory
arrays via $readmemh. This script creates those hex files from a boot
binary image, including bootinfo records needed for Linux boot.

Generated files (placed alongside the input binary):
  dmem.hex  - Data memory (32-bit words, indexed by byte_addr >> 2)
  imem.hex  - Instruction memory (16-bit words, indexed by byte_addr)
  aregs.hex - Address registers (aregs[7] = initial SSP)
  dregs.hex - Data registers (all zero)
"""
import sys
import os

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <boot.bin> [output_dir]")
        sys.exit(1)

    boot_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(boot_path) or '.'

    with open(boot_path, 'rb') as f:
        boot_data = f.read()

    print(f"Boot image: {len(boot_data)} bytes ({len(boot_data)//1024} KB)")

    # Pad to multiple of 2 bytes
    if len(boot_data) % 2:
        boot_data += b'\x00'

    # dmem: 32-bit words, big-endian, indexed by (byte_addr >> 2)
    #   word = {byte[4N], byte[4N+1], byte[4N+2], byte[4N+3]}
    # imem: 16-bit words, indexed by byte_addr (only even entries used)
    dmem = {}
    imem = {}

    # Pad to multiple of 4 bytes for 32-bit dmem
    while len(boot_data) % 4:
        boot_data += b'\x00'

    for i in range(0, len(boot_data), 2):
        word16 = (boot_data[i] << 8) | boot_data[i+1]  # Big-endian 16-bit
        imem[i] = word16  # imem index = byte_addr (even)

    for i in range(0, len(boot_data), 4):
        word32 = (boot_data[i] << 24) | (boot_data[i+1] << 16) | \
                 (boot_data[i+2] << 8) | boot_data[i+3]  # Big-endian 32-bit
        dmem[i >> 2] = word32  # dmem index = byte_addr >> 2

    # Add bootinfo records at _end (kernel BSS end)
    # Auto-detect from System.map if available, else use provided/default address
    bi_addr = None
    # Look for System.map in parent directory (../linux/System.map relative to output)
    sysmap_candidates = [
        os.path.join(os.path.dirname(boot_path), '..', 'linux', 'System.map'),
        os.path.join(output_dir, '..', 'linux', 'System.map'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'linux', 'System.map'),
    ]
    for sysmap_path in sysmap_candidates:
        if os.path.exists(sysmap_path):
            with open(sysmap_path) as sf:
                for line in sf:
                    parts = line.strip().split()
                    if len(parts) >= 3 and parts[2] == '_end':
                        bi_addr = int(parts[0], 16)
                        print(f"Found _end = 0x{bi_addr:08x} from {sysmap_path}")
                        break
            if bi_addr is not None:
                break
    if bi_addr is None:
        bi_addr = 0x4db000  # Fallback
        print(f"Warning: System.map not found, using default bootinfo addr 0x{bi_addr:08x}")
    bootinfo = []

    def add_bi_record(tag, data_words):
        """Add a bootinfo record. data_words is list of 16-bit values."""
        size = 4 + len(data_words) * 2  # header + data
        # Pad to multiple of 4
        if size % 4:
            data_words = list(data_words) + [0]
            size += 2
        bootinfo.append((tag, size, data_words))

    # BI_MACHTYPE (tag=1): MACH_VIRT = 14 (kernel built with CONFIG_VIRT)
    add_bi_record(1, [0x0000, 0x000e])
    # BI_CPUTYPE (tag=2): CPU_68030 = 0x02
    add_bi_record(2, [0x0000, 0x0002])
    # BI_FPUTYPE (tag=3): FPU_68882 = 0x02
    add_bi_record(3, [0x0000, 0x0002])
    # BI_MMUTYPE (tag=4): MMU_68030 = 0x02
    add_bi_record(4, [0x0000, 0x0002])
    # BI_MEMCHUNK (tag=5): RAM 0x00000000, size 64MB (0x04000000)
    add_bi_record(5, [0x0000, 0x0000, 0x0400, 0x0000])
    # BI_VIRT_GF_PIC_BASE (tag=0x8001): mmio=0x04000000, irq=1 (IRQ_AUTO_1)
    # 6 PICs at 0x1000 apart, mapped to CPU autovector levels 1-6
    add_bi_record(0x8001, [0x0400, 0x0000, 0x0000, 0x0001])
    # BI_VIRT_GF_RTC_BASE (tag=0x8002): mmio=0x04006000, irq=168 (IRQ_USER+5*32)
    # Goldfish timer on PIC #5 (IPL6), bit 0 -> IRQ_USER(8) + 160 = 168
    add_bi_record(0x8002, [0x0400, 0x6000, 0x0000, 0x00a8])
    # BI_VIRT_GF_TTY_BASE (tag=0x8003): mmio=0x04008000, irq=8 (IRQ_USER+0*32)
    # Goldfish TTY on PIC #0 (IPL1), bit 0 -> IRQ_USER(8) + 0 = 8
    # NOTE: Must match testbench GF_TTY_BASE. RTC platform device occupies
    # rtc.mmio+0x1000 = 0x04007000, so TTY is at 0x04008000.
    add_bi_record(0x8003, [0x0400, 0x8000, 0x0000, 0x0008])
    # BI_VIRT_CTRL_BASE (tag=0x8005): mmio=0x04009000, irq=0
    # Virtual control device for halt/reset (testbench ignores writes)
    add_bi_record(0x8005, [0x0400, 0x9000, 0x0000, 0x0000])
    # BI_RNG_SEED (tag=8): Random seed to initialize CRNG
    # Format: u16 length (BE), followed by seed bytes
    # Skips expensive jitter entropy collection during boot (~40M cycles saved)
    rng_seed = bytes(range(1, 65))  # 64 bytes of deterministic "random" data
    rng_data = len(rng_seed).to_bytes(2, 'big') + rng_seed
    # Pad to multiple of 2
    if len(rng_data) % 2:
        rng_data += b'\x00'
    rng_words = []
    for j in range(0, len(rng_data), 2):
        rng_words.append((rng_data[j] << 8) | rng_data[j+1])
    # Pad data to make total record size multiple of 4
    rng_total = 4 + len(rng_words) * 2
    if rng_total % 4:
        rng_words.append(0)
    add_bi_record(8, rng_words)
    # BI_COMMAND_LINE (tag=7): kernel command line
    # console=ttyGF0 = goldfish TTY as main console
    # lpj= pre-sets loops_per_jiffy to skip calibrate_delay (~24M cycles saved)
    cmdline = b"console=ttyGF0 lpj=250000\x00"
    # Pad to multiple of 2
    if len(cmdline) % 2:
        cmdline += b'\x00'
    cmd_words = []
    for j in range(0, len(cmdline), 2):
        cmd_words.append((cmdline[j] << 8) | cmdline[j+1])
    # Pad data to make total record size multiple of 4
    data_size = len(cmd_words) * 2
    total = 4 + data_size
    if total % 4:
        cmd_words.append(0)
    add_bi_record(7, cmd_words)
    # BI_LAST (tag=0)
    bootinfo.append((0, 4, []))

    # Write bootinfo to dmem (32-bit words)
    # Each bootinfo record: tag (16-bit) + size (16-bit) + data_words (16-bit each)
    # Build bootinfo as 16-bit halfwords first, then pack into 32-bit words
    bi_halfwords = {}  # key: halfword address (byte_addr >> 1), value: 16-bit word
    addr = bi_addr
    for tag, size, data_words in bootinfo:
        bi_halfwords[addr >> 1] = tag
        bi_halfwords[(addr >> 1) + 1] = size
        for k, w in enumerate(data_words):
            bi_halfwords[(addr >> 1) + 2 + k] = w
        addr += size

    # Pack halfwords into 32-bit dmem entries
    for hw_addr, hw_val in bi_halfwords.items():
        byte_addr = hw_addr * 2
        word_idx = byte_addr >> 2
        if word_idx not in dmem:
            dmem[word_idx] = 0
        if byte_addr & 2:  # Lower halfword
            dmem[word_idx] = (dmem[word_idx] & 0xFFFF0000) | (hw_val & 0xFFFF)
        else:  # Upper halfword
            dmem[word_idx] = (dmem[word_idx] & 0x0000FFFF) | ((hw_val & 0xFFFF) << 16)

    print(f"Bootinfo records at 0x{bi_addr:08x} - 0x{addr:08x}")

    # Write dmem.hex (32-bit words)
    dmem_path = os.path.join(output_dir, 'dmem.hex')
    with open(dmem_path, 'w') as f:
        # Write in sparse format - only non-zero entries
        last_addr = -2
        for addr in sorted(dmem.keys()):
            if dmem[addr] == 0:
                continue
            if addr != last_addr + 1:
                f.write(f"@{addr:x}\n")
            f.write(f"{dmem[addr]:08x}\n")
            last_addr = addr
    print(f"Written: {dmem_path}")

    # Write imem.hex
    # imem is indexed by byte address with only even entries used (0, 2, 4, ...).
    # Every entry needs an explicit @ address since $readmemh fills consecutive
    # indices without @ markers.
    imem_path = os.path.join(output_dir, 'imem.hex')
    with open(imem_path, 'w') as f:
        for addr in sorted(imem.keys()):
            if imem[addr] == 0:
                continue
            f.write(f"@{addr:x} {imem[addr]:04x}\n")
    print(f"Written: {imem_path}")

    # Write aregs.hex - aregs[7] = 0x03FFFFF0 (initial SSP)
    aregs_path = os.path.join(output_dir, 'aregs.hex')
    with open(aregs_path, 'w') as f:
        f.write("@7\n")
        f.write("03fffff0\n")
    print(f"Written: {aregs_path}")

    # Write dregs.hex - all zeros (empty file is fine but $readmemh needs it to exist)
    dregs_path = os.path.join(output_dir, 'dregs.hex')
    with open(dregs_path, 'w') as f:
        pass  # Empty file
    print(f"Written: {dregs_path}")

if __name__ == '__main__':
    main()
