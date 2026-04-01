#!/usr/bin/env python3
"""
Generate J4/SH4 TLB configurations for testing.

Usage:
    python3 generate_tlb_config.py [config_name]

Config names:
    identity      - Identity mapping (VPN=PPN), MMU effectively passthrough
    offset        - Non-identity mapping with fixed offset (VPN -> PPN+offset)
    scrambled     - Randomized mapping to verify translation is working
    minimal       - Only essential entries for test code

Creates ITLB (4 entries) and UTLB (64 entries) hex files.
"""

import sys
import os
import random

def generate_identity_config():
    """Identity mapping - VPN equals PPN for all entries."""
    utlb_entries = []
    for i in range(64):
        utlb_entries.append({
            'vpn': i,       # Virtual page number
            'asid': 0,      # Address space ID
            'ppn': i,       # Physical page number (same as VPN)
            'sz': 0,        # Page size: 1KB
            'pr': 2,        # Protection: RW for kernel+user
            'c': 0,         # Cacheable: no
            'd': 1,         # Dirty: yes (writable)
            'sh': 1,        # Shared: yes (global)
            'wt': 0,        # Write-through: no
            'v': 1,         # Valid: yes
        })

    itlb_entries = []
    for i in range(4):
        itlb_entries.append({
            'vpn': i,
            'asid': 0,
            'ppn': i,       # Identity mapping
            'sz': 0,
            'pr': 2,
            'c': 0,
            'sh': 1,
            'v': 1,
        })

    return utlb_entries, itlb_entries, "Identity mapping (VPN=PPN)"


def generate_offset_config(offset=16):
    """Non-identity UTLB mapping - VPN maps to PPN+offset.

    ITLB is kept as identity mapping so instruction fetch works correctly.
    UTLB uses offset mapping to verify data translation is working.
    """
    utlb_entries = []
    for i in range(64):
        utlb_entries.append({
            'vpn': i,
            'asid': 0,
            'ppn': (i + offset) % 4096,  # Offset mapping for data
            'sz': 0,
            'pr': 2,
            'c': 0,
            'd': 1,
            'sh': 1,
            'wt': 0,
            'v': 1,
        })

    # ITLB: Keep identity mapping for instruction fetch
    itlb_entries = []
    for i in range(4):
        itlb_entries.append({
            'vpn': i,
            'asid': 0,
            'ppn': i,  # Identity for ITLB - code fetch must work!
            'sz': 0,
            'pr': 2,
            'c': 0,
            'sh': 1,
            'v': 1,
        })

    return utlb_entries, itlb_entries, f"UTLB offset +{offset}, ITLB identity"


def generate_scrambled_config(seed=42):
    """Pseudo-random UTLB mapping to prove translation is working.

    ITLB is kept as identity mapping so instruction fetch works correctly.
    UTLB uses scrambled mapping to verify data translation.
    """
    random.seed(seed)

    # Create a permuted mapping
    ppn_map = list(range(64))
    random.shuffle(ppn_map)

    utlb_entries = []
    for i in range(64):
        utlb_entries.append({
            'vpn': i,
            'asid': 0,
            'ppn': ppn_map[i],  # Scrambled mapping for data
            'sz': 0,
            'pr': 2,
            'c': 0,
            'd': 1,
            'sh': 1,
            'wt': 0,
            'v': 1,
        })

    # ITLB: Keep identity mapping for instruction fetch
    itlb_entries = []
    for i in range(4):
        itlb_entries.append({
            'vpn': i,
            'asid': 0,
            'ppn': i,  # Identity for ITLB - code fetch must work!
            'sz': 0,
            'pr': 2,
            'c': 0,
            'sh': 1,
            'v': 1,
        })

    return utlb_entries, itlb_entries, f"UTLB scrambled (seed={seed}), ITLB identity"


def generate_minimal_config():
    """Minimal config - only essential entries, rest invalid."""
    utlb_entries = []
    for i in range(64):
        if i < 8:
            # First 8 entries: identity mapping for test code
            utlb_entries.append({
                'vpn': i,
                'asid': 0,
                'ppn': i,
                'sz': 0,
                'pr': 2,
                'c': 0,
                'd': 1,
                'sh': 1,
                'wt': 0,
                'v': 1,
            })
        elif i < 16:
            # Next 8 entries: non-identity mapping for data testing
            utlb_entries.append({
                'vpn': i,
                'asid': 0,
                'ppn': i + 32,  # Map to different physical location
                'sz': 0,
                'pr': 2,
                'c': 0,
                'd': 1,
                'sh': 1,
                'wt': 0,
                'v': 1,
            })
        else:
            # Rest: invalid entries
            utlb_entries.append({
                'vpn': 0,
                'asid': 0,
                'ppn': 0,
                'sz': 0,
                'pr': 0,
                'c': 0,
                'd': 0,
                'sh': 0,
                'wt': 0,
                'v': 0,  # Invalid
            })

    itlb_entries = []
    for i in range(4):
        itlb_entries.append({
            'vpn': i,
            'asid': 0,
            'ppn': i,  # Identity for instruction fetch
            'sz': 0,
            'pr': 2,
            'c': 0,
            'sh': 1,
            'v': 1,
        })

    return utlb_entries, itlb_entries, "Minimal config (8 identity + 8 offset)"


def generate_translation_test_config():
    """
    Config specifically designed to verify translation is working.

    Key features:
    - VPN 0-15: Map to PPN 16-31 (offset of +16)
    - This means physical memory at 0-0x3FFF will be accessed via VA 0x4000-0x7FFF
    - Test code at physical 0 will appear at virtual 0x4000
    """
    utlb_entries = []

    for i in range(64):
        if i < 16:
            # Map VA 0-0x3FFF to PA 0x4000-0x7FFF (inverted for test verification)
            # When code runs at VA=0, it accesses PA=0x4000
            # But we want test code at PA=0 to run at VA=0
            # So: VPN i -> PPN i (identity for code segment)
            utlb_entries.append({
                'vpn': i,
                'asid': 0,
                'ppn': i,  # Identity for now
                'sz': 0,
                'pr': 2,
                'c': 0,
                'd': 1,
                'sh': 1,
                'wt': 0,
                'v': 1,
            })
        elif i < 32:
            # Map VA 0x4000-0x7FFF to PA 0 (for data access tests)
            # VPN 16-31 -> PPN 0-15
            utlb_entries.append({
                'vpn': i,
                'asid': 0,
                'ppn': i - 16,  # Map VA 0x4xxx to PA 0x0xxx
                'sz': 0,
                'pr': 2,
                'c': 0,
                'd': 1,
                'sh': 1,
                'wt': 0,
                'v': 1,
            })
        elif i < 48:
            # Map VA 0x8000-0xBFFF to PA 0x8000-0xBFFF (for data stores)
            utlb_entries.append({
                'vpn': i,
                'asid': 0,
                'ppn': i + 32,  # Large offset
                'sz': 0,
                'pr': 2,
                'c': 0,
                'd': 1,
                'sh': 1,
                'wt': 0,
                'v': 1,
            })
        else:
            # Rest: identity mapping
            utlb_entries.append({
                'vpn': i,
                'asid': 0,
                'ppn': i,
                'sz': 0,
                'pr': 2,
                'c': 0,
                'd': 1,
                'sh': 1,
                'wt': 0,
                'v': 1,
            })

    itlb_entries = []
    for i in range(4):
        itlb_entries.append({
            'vpn': i,
            'asid': 0,
            'ppn': i,  # Identity for instruction fetch
            'sz': 0,
            'pr': 2,
            'c': 0,
            'sh': 1,
            'v': 1,
        })

    return utlb_entries, itlb_entries, "Translation test (VPN 16-31 -> PPN 0-15)"


CONFIGS = {
    'identity': generate_identity_config,
    'offset': lambda: generate_offset_config(16),
    'offset32': lambda: generate_offset_config(32),
    'scrambled': generate_scrambled_config,
    'minimal': generate_minimal_config,
    'translation_test': generate_translation_test_config,
}


def write_config(utlb_entries, itlb_entries, output_dir='.'):
    """Write TLB configuration to hex files."""

    # UTLB files
    fields = ['vpn', 'asid', 'ppn', 'sz', 'pr', 'c', 'd', 'sh', 'wt', 'v']
    for field in fields:
        filepath = os.path.join(output_dir, f'utlb_{field}.hex')
        with open(filepath, 'w') as f:
            for entry in utlb_entries:
                f.write(f'{entry[field]:08x}\n')

    # ITLB files (no d, wt fields)
    itlb_fields = ['vpn', 'asid', 'ppn', 'sz', 'pr', 'c', 'sh', 'v']
    for field in itlb_fields:
        filepath = os.path.join(output_dir, f'itlb_{field}.hex')
        with open(filepath, 'w') as f:
            for entry in itlb_entries:
                f.write(f'{entry[field]:08x}\n')


def print_config_summary(utlb_entries, itlb_entries, description):
    """Print a summary of the TLB configuration."""
    print(f"\nTLB Configuration: {description}")
    print("=" * 70)
    print("\nUTLB Summary (64 entries):")
    print("Entry | VPN      | PPN      | SZ | V | Description")
    print("-" * 60)

    prev_desc = None
    group_start = 0

    for i, entry in enumerate(utlb_entries):
        vpn_ppn_diff = entry['ppn'] - entry['vpn']
        if entry['v'] == 0:
            desc = "Invalid"
        elif vpn_ppn_diff == 0:
            desc = "Identity"
        else:
            desc = f"Offset {vpn_ppn_diff:+d}"

        if desc != prev_desc:
            if prev_desc is not None and i > group_start + 1:
                print(f"  ... ({i - group_start - 1} more entries)")
            print(f"{i:5} | {entry['vpn']:06x}   | {entry['ppn']:06x}   | {entry['sz']:2} | {entry['v']} | {desc}")
            prev_desc = desc
            group_start = i

    if prev_desc is not None and len(utlb_entries) > group_start + 1:
        print(f"  ... ({len(utlb_entries) - group_start - 1} more entries)")

    print("\nITLB Summary (4 entries):")
    for i, entry in enumerate(itlb_entries):
        vpn_ppn_diff = entry['ppn'] - entry['vpn']
        if entry['v'] == 0:
            desc = "Invalid"
        elif vpn_ppn_diff == 0:
            desc = "Identity"
        else:
            desc = f"Offset {vpn_ppn_diff:+d}"
        print(f"{i:5} | {entry['vpn']:06x}   | {entry['ppn']:06x}   | {entry['sz']:2} | {entry['v']} | {desc}")


def main():
    config_name = sys.argv[1] if len(sys.argv) > 1 else 'identity'
    output_dir = sys.argv[2] if len(sys.argv) > 2 else '.'

    if config_name == 'list':
        print("Available configurations:")
        for name in CONFIGS:
            print(f"  {name}")
        return

    if config_name not in CONFIGS:
        print(f"Unknown config: {config_name}")
        print(f"Available: {', '.join(CONFIGS.keys())}")
        sys.exit(1)

    utlb_entries, itlb_entries, description = CONFIGS[config_name]()

    write_config(utlb_entries, itlb_entries, output_dir)
    print_config_summary(utlb_entries, itlb_entries, description)
    print(f"\nWrote TLB config files to {output_dir}/")


if __name__ == '__main__':
    main()
