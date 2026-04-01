#!/usr/bin/env python3
"""Generate TLB config with VPN=12 -> PPN=8 for translation-verify test."""

# UTLB: 64 entries
# Entry 12 maps VPN=12 to PPN=8 (VA 0x3000 -> PA 0x2000)
# All other entries: identity mapping

with open('utlb_vpn.hex', 'w') as f:
    for i in range(64):
        f.write(f'{i:08x}\n')  # VPN = i

with open('utlb_asid.hex', 'w') as f:
    for i in range(64):
        f.write('00000000\n')  # ASID = 0

with open('utlb_v.hex', 'w') as f:
    for i in range(64):
        f.write('00000001\n')  # V = 1 (valid)

# This is the key: entry 12 maps VPN=12 to PPN=8 (instead of identity PPN=12)
with open('utlb_ppn.hex', 'w') as f:
    for i in range(64):
        if i == 12:
            # VPN=12 (VA 0x3000) -> PPN=8 (PA 0x2000)
            # PPN[28:10] = 8 for 4KB page at PA 0x2000
            f.write('00000008\n')
        else:
            f.write(f'{i:08x}\n')  # Identity mapping

with open('utlb_sz.hex', 'w') as f:
    for i in range(64):
        f.write('00000001\n')  # SZ=1 (4KB pages)

with open('utlb_pr.hex', 'w') as f:
    for i in range(64):
        f.write('00000002\n')  # PR=2 (RW)

with open('utlb_c.hex', 'w') as f:
    for i in range(64):
        f.write('00000000\n')  # C = 0

with open('utlb_d.hex', 'w') as f:
    for i in range(64):
        f.write('00000001\n')  # D = 1 (dirty)

with open('utlb_sh.hex', 'w') as f:
    for i in range(64):
        f.write('00000001\n')  # SH = 1 (shared/global)

with open('utlb_wt.hex', 'w') as f:
    for i in range(64):
        f.write('00000000\n')  # WT = 0

# ITLB: 4 entries - identity mapping for instruction fetch
for arr in ['itlb_vpn', 'itlb_ppn']:
    with open(f'{arr}.hex', 'w') as f:
        for i in range(4):
            f.write(f'{i:08x}\n')

for arr in ['itlb_asid', 'itlb_c']:
    with open(f'{arr}.hex', 'w') as f:
        for i in range(4):
            f.write('00000000\n')

for arr in ['itlb_v', 'itlb_sh']:
    with open(f'{arr}.hex', 'w') as f:
        for i in range(4):
            f.write('00000001\n')

for arr in ['itlb_sz', 'itlb_pr']:
    with open(f'{arr}.hex', 'w') as f:
        for i in range(4):
            if arr == 'itlb_sz':
                f.write('00000001\n')
            else:
                f.write('00000002\n')

print("TLB config generated with VPN=12 -> PPN=8 mapping")
