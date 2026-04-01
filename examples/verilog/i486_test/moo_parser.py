#!/usr/bin/env python3
"""
MOO (Machine Opcode Operation) file parser for i486/80386 tests.
Based on the MOO format specification v1.1.
"""

import struct
import gzip
from pathlib import Path


class MooParser:
    """Parser for MOO binary test files."""

    # 16-bit register names in bitmask order
    REGS16 = ['ax', 'cx', 'dx', 'bx', 'sp', 'bp', 'si', 'di',
              'es', 'cs', 'ss', 'ds', 'ip', 'flags']

    # 32-bit register names in bitmask order (386+)
    REGS32 = ['eax', 'ecx', 'edx', 'ebx', 'esp', 'ebp', 'esi', 'edi',
              'eip', 'eflags', 'cr0', 'cr2', 'cr3', 'dr0', 'dr1', 'dr2',
              'dr3', 'dr6', 'dr7', 'fs', 'gs']

    def __init__(self):
        self.tests = []
        self.cpu_type = None
        self.opcode = None

    def parse_file(self, filepath):
        """Parse a MOO file and return list of tests."""
        filepath = Path(filepath)

        # Handle gzip compression
        if filepath.suffix == '.gz':
            with gzip.open(filepath, 'rb') as f:
                data = f.read()
        else:
            with open(filepath, 'rb') as f:
                data = f.read()

        return self.parse_data(data)

    def parse_data(self, data):
        """Parse MOO binary data and return list of tests."""
        self.tests = []
        pos = 0

        while pos < len(data):
            if pos + 8 > len(data):
                break

            # Read chunk header (type + length)
            chunk_type = data[pos:pos+4].decode('ascii')
            chunk_len = struct.unpack('<I', data[pos+4:pos+8])[0]
            pos += 8

            chunk_data = data[pos:pos+chunk_len]
            pos += chunk_len

            if chunk_type == 'MOO ':
                self._parse_moo_header(chunk_data)
            elif chunk_type == 'META':
                self._parse_meta(chunk_data)
            elif chunk_type == 'TEST':
                test = self._parse_test(chunk_data)
                if test:
                    self.tests.append(test)

        return self.tests

    def _parse_moo_header(self, data):
        """Parse MOO header chunk."""
        if len(data) >= 12:
            major, minor, _, _, test_count = struct.unpack('<BBBBI', data[:8])
            self.cpu_type = data[8:12].decode('ascii').strip()

    def _parse_meta(self, data):
        """Parse META chunk."""
        if len(data) >= 4:
            self.opcode = struct.unpack('<I', data[0:4])[0]

    def _parse_test(self, data):
        """Parse a TEST chunk containing subchunks."""
        test = {
            'name': '',
            'bytes': [],
            'initial': {'regs': {}, 'ram': []},
            'final': {'regs': {}, 'ram': []},
            'idx': 0
        }

        pos = 0

        # Read test index
        if len(data) >= 4:
            test['idx'] = struct.unpack('<I', data[0:4])[0]
            pos = 4

        current_state = None  # 'initial' or 'final'

        while pos + 8 <= len(data):
            chunk_type = data[pos:pos+4].decode('ascii')
            chunk_len = struct.unpack('<I', data[pos+4:pos+8])[0]
            pos += 8

            if pos + chunk_len > len(data):
                break

            chunk_data = data[pos:pos+chunk_len]
            pos += chunk_len

            if chunk_type == 'NAME':
                # Length-prefixed ASCII string
                if len(chunk_data) > 0:
                    name_len = chunk_data[0]
                    name_bytes = chunk_data[1:1+name_len]
                    # Strip null bytes and decode - strip from both ends and replace internal nulls
                    name_str = name_bytes.decode('ascii', errors='replace').strip('\x00').replace('\x00', '')
                    test['name'] = name_str if name_str else f"test_{test['idx']}"

            elif chunk_type == 'BYTS':
                # BYTS chunk has a 4-byte length prefix, then the actual bytes
                if len(chunk_data) >= 4:
                    byte_count = struct.unpack('<I', chunk_data[0:4])[0]
                    test['bytes'] = list(chunk_data[4:4+byte_count])
                else:
                    test['bytes'] = list(chunk_data)

            elif chunk_type == 'INIT':
                current_state = 'initial'
                self._parse_state_chunk(chunk_data, test['initial'])

            elif chunk_type == 'FINA':
                current_state = 'final'
                self._parse_state_chunk(chunk_data, test['final'])

            elif chunk_type == 'REGS':
                if current_state:
                    self._parse_regs16(chunk_data, test[current_state]['regs'])

            elif chunk_type == 'RG32':
                if current_state:
                    self._parse_regs32(chunk_data, test[current_state]['regs'])

            elif chunk_type == 'RAM ':
                if current_state:
                    self._parse_ram(chunk_data, test[current_state])

            elif chunk_type == 'HASH':
                test['hash'] = chunk_data.hex()

        return test

    def _parse_state_chunk(self, data, state):
        """Parse INIT or FINA state containing subchunks."""
        pos = 0
        while pos + 8 <= len(data):
            chunk_type = data[pos:pos+4].decode('ascii')
            chunk_len = struct.unpack('<I', data[pos+4:pos+8])[0]
            pos += 8

            if pos + chunk_len > len(data):
                break

            chunk_data = data[pos:pos+chunk_len]
            pos += chunk_len

            if chunk_type == 'REGS':
                self._parse_regs16(chunk_data, state['regs'])
            elif chunk_type == 'RG32':
                self._parse_regs32(chunk_data, state['regs'])
            elif chunk_type == 'RAM ':
                self._parse_ram(chunk_data, state)

    def _parse_regs16(self, data, regs):
        """Parse 16-bit register data with bitmask."""
        if len(data) < 2:
            return

        bitmask = struct.unpack('<H', data[0:2])[0]
        pos = 2

        for i, reg_name in enumerate(self.REGS16):
            if bitmask & (1 << i):
                if pos + 2 <= len(data):
                    value = struct.unpack('<H', data[pos:pos+2])[0]
                    regs[reg_name] = value
                    pos += 2

    def _parse_regs32(self, data, regs):
        """Parse 32-bit register data with bitmask."""
        if len(data) < 4:
            return

        bitmask = struct.unpack('<I', data[0:4])[0]
        pos = 4

        for i, reg_name in enumerate(self.REGS32):
            if bitmask & (1 << i):
                if pos + 4 <= len(data):
                    value = struct.unpack('<I', data[pos:pos+4])[0]
                    regs[reg_name] = value
                    pos += 4

    def _parse_ram(self, data, state):
        """Parse RAM address-value pairs (5 bytes each).

        RAM chunk format:
        - 4 bytes: entry count
        - Then N entries of 5 bytes each (4-byte address + 1-byte value)
        """
        if len(data) < 4:
            return

        # First 4 bytes are the entry count
        entry_count = struct.unpack('<I', data[0:4])[0]
        pos = 4
        ram_list = []

        while pos + 5 <= len(data) and len(ram_list) < entry_count:
            # 4-byte address + 1-byte value
            addr = struct.unpack('<I', data[pos:pos+4])[0]
            value = data[pos+4]
            ram_list.append([addr, value])
            pos += 5

        state['ram'] = ram_list


def parse_moo_file(filepath):
    """Convenience function to parse a MOO file."""
    parser = MooParser()
    return parser.parse_file(filepath)


if __name__ == '__main__':
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python moo_parser.py <file.MOO.gz>")
        sys.exit(1)

    tests = parse_moo_file(sys.argv[1])
    print(f"Parsed {len(tests)} tests")

    if tests:
        # Print first test as example
        print(json.dumps(tests[0], indent=2))
