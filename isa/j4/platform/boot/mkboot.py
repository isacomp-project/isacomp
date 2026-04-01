#!/usr/bin/env python3
"""
J4 Boot Image Builder
Combines: Boot ROM + FDT + Kernel into umem.hex for $readmemh

Memory Layout:
  0x00000000 - Boot ROM code
  0x00000100 - Device Tree Blob (FDT)
  0x00001000 - Kernel (vmlinux.bin)
  0x00002000 - Kernel entry point (_stext)

Usage: python3 mkboot.py <vmlinux.bin> <dtb> <output_dir>
"""

import sys
import struct
import os

def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <vmlinux.bin> <dtb> <output_dir>")
        print(f"  Creates umem.hex and other hex files in output_dir")
        sys.exit(1)

    kernel_path = sys.argv[1]
    dtb_path = sys.argv[2]
    output_dir = sys.argv[3]

    # Read kernel
    with open(kernel_path, 'rb') as f:
        kernel_data = f.read()
    print(f"Kernel: {len(kernel_data)} bytes")

    # Read DTB
    with open(dtb_path, 'rb') as f:
        dtb_data = f.read()
    print(f"DTB: {len(dtb_data)} bytes")

    # Boot ROM code (hand-assembled SH-4 big-endian)
    # This is the minimal boot ROM that:
    # 1. Sets VBR to 0 (exception vectors at RAM start)
    # 2. Sets FPSCR for FPU
    # 3. Sets R4 = FDT address (0x100)
    # 4. Jumps to kernel entry (0x2000)
    #
    # SH-4 MOV.L @(disp,PC),Rn: target = ((PC + 4) & ~3) + disp * 4
    #
    # Layout:
    #   0x00: mov.l @(6*4,PC), r1  -> load from ((0+4)&~3) + 24 = 28 = 0x1C (vbr_init)
    #   0x02: ldc r1, vbr
    #   0x04: mov.l @(6*4,PC), r1  -> load from ((4+4)&~3) + 24 = 32 = 0x20 (fpscr_init)
    #   0x06: lds r1, fpscr
    #   0x08: mov.l @(6*4,PC), r4  -> load from ((8+4)&~3) + 24 = 36 = 0x24 (fdt_addr)
    #   0x0A: mov #0, r5
    #   0x0C: mov #0, r6
    #   0x0E: mov #0, r7
    #   0x10: mov.l @(4*4,PC), r0  -> load from ((0x10+4)&~3) + 16 = 0x14 + 16 = 0x24... no wait
    #         Actually: ((0x10+4)&~3) = 0x14, + 4*4 = 16 = 0x24 + 16 - 0x14 = no...
    #         Let me recalculate: target = 0x28, base = 0x14, disp = (0x28-0x14)/4 = 0x14/4 = 5
    #   0x12: jmp @r0
    #   0x14: nop
    #   0x16: nop (padding)
    #   0x18: nop (padding)
    #   0x1A: nop (padding)
    #   0x1C: vbr_init = 0x00000000
    #   0x20: fpscr_init = 0x00040001
    #   0x24: fdt_addr = 0x00000100
    #   0x28: kernel_addr = 0x00002000

    bootrom = bytearray()

    # 0x00: mov.l @(7*4,PC), r1  -> load from ((0+4)&~3) + 28 = 32 = 0x1C (but need 4 & ~3 = 4, + 28 = 0x20)
    # Let me be more careful:
    # At PC=0x00: base = (0+4) & ~3 = 4
    # For vbr_init at 0x1C: disp = (0x1C - 4) / 4 = 0x18/4 = 6
    bootrom += bytes([0xd1, 0x06])  # mov.l @(6,PC), r1 -> vbr_init at 0x1C
    bootrom += bytes([0x40, 0x2e])  # ldc r1, vbr

    # At PC=0x04: base = (4+4) & ~3 = 8
    # For fpscr_init at 0x20: disp = (0x20 - 8) / 4 = 0x18/4 = 6
    bootrom += bytes([0xd1, 0x06])  # mov.l @(6,PC), r1 -> fpscr_init at 0x20
    bootrom += bytes([0x41, 0x6a])  # lds r1, fpscr

    # At PC=0x08: base = (8+4) & ~3 = 12 = 0x0C
    # For fdt_addr at 0x24: disp = (0x24 - 0x0C) / 4 = 0x18/4 = 6
    bootrom += bytes([0xd4, 0x06])  # mov.l @(6,PC), r4 -> fdt_addr at 0x24
    bootrom += bytes([0xe5, 0x00])  # mov #0, r5

    # 0x0C
    bootrom += bytes([0xe6, 0x00])  # mov #0, r6
    bootrom += bytes([0xe7, 0x00])  # mov #0, r7

    # At PC=0x10: base = (0x10+4) & ~3 = 0x14
    # For kernel_addr at 0x28: disp = (0x28 - 0x14) / 4 = 0x14/4 = 5
    bootrom += bytes([0xd0, 0x05])  # mov.l @(5,PC), r0 -> kernel_addr at 0x28
    bootrom += bytes([0x40, 0x2b])  # jmp @r0

    # 0x14: delay slot
    bootrom += bytes([0x00, 0x09])  # nop

    # 0x16: padding to align constants to 4-byte boundary
    bootrom += bytes([0x00, 0x09])  # nop (padding)
    bootrom += bytes([0x00, 0x09])  # nop (padding)
    bootrom += bytes([0x00, 0x09])  # nop (padding)

    # 0x1C: vbr_init
    bootrom += struct.pack('>I', 0x00000000)

    # 0x20: fpscr_init
    bootrom += struct.pack('>I', 0x00040001)

    # 0x24: fdt_addr
    bootrom += struct.pack('>I', 0x00000100)

    # 0x28: kernel_addr
    bootrom += struct.pack('>I', 0x00002000)

    print(f"Boot ROM: {len(bootrom)} bytes")

    # Build the complete image
    # Total size = kernel offset + kernel size
    image_size = 0x1000 + len(kernel_data)
    image = bytearray(image_size)

    # Place boot ROM at 0x00
    image[0:len(bootrom)] = bootrom

    # Place DTB at 0x100
    if 0x100 + len(dtb_data) > 0x1000:
        print(f"ERROR: DTB too large ({len(dtb_data)} bytes), overlaps kernel")
        sys.exit(1)
    image[0x100:0x100+len(dtb_data)] = dtb_data

    # Place kernel at 0x1000
    image[0x1000:0x1000+len(kernel_data)] = kernel_data

    # Create output directory if needed
    os.makedirs(output_dir, exist_ok=True)

    # Write umem.hex - one word per line in hex format
    umem_path = os.path.join(output_dir, 'umem.hex')
    with open(umem_path, 'w') as f:
        for i in range(0, len(image), 4):
            if i + 4 <= len(image):
                word = struct.unpack('>I', image[i:i+4])[0]
            else:
                # Pad remaining bytes
                remaining = image[i:]
                word = 0
                for j, b in enumerate(remaining):
                    word |= b << (24 - j*8)
            f.write(f'{word:08x}\n')

    # Create empty hex files for registers
    empty_files = ['rf.hex', 'rf_bank.hex', 'fpr.hex', 'fr.hex',
                   'itlb_v.hex', 'utlb_asid.hex', 'utlb_c.hex', 'utlb_d.hex',
                   'utlb_ppn.hex', 'utlb_pr.hex', 'utlb_sh.hex', 'utlb_sz.hex',
                   'utlb_v.hex', 'utlb_vpn.hex', 'utlb_wt.hex']
    for name in empty_files:
        path = os.path.join(output_dir, name)
        with open(path, 'w') as f:
            f.write('00000000\n')

    print(f"\nCreated: {umem_path} ({len(image)//4} words, {len(image)//1024} KB)")
    print(f"Created empty register hex files in {output_dir}")
    print(f"\nMemory Layout:")
    print(f"  0x00000000 - Boot ROM (entry point)")
    print(f"  0x00000100 - FDT ({len(dtb_data)} bytes)")
    print(f"  0x00001000 - Kernel start")
    print(f"  0x00002000 - Kernel entry (_stext)")
    print(f"\nTo run simulation:")
    print(f"  cd {output_dir} && ./obj_dir/Vlinux_boot_tb +entry=00000000")

if __name__ == '__main__':
    main()
