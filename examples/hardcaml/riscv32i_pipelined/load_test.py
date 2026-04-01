#!/usr/bin/env python3
"""Convert Intel HEX test file to umem.hex for simulation."""
import sys

hex_file = sys.argv[1]
data = {}
with open(hex_file, 'r') as f:
    for line in f:
        line = line.strip()
        if not line or line[0] != ':':
            continue
        count = int(line[1:3], 16)
        addr = int(line[3:7], 16)
        rtype = int(line[7:9], 16)
        if rtype != 0:
            continue
        for i in range(count):
            data[addr + i] = int(line[9+2*i:11+2*i], 16)

words = []
max_addr = max(data.keys()) if data else 0
for a in range(0, max_addr + 4, 4):
    b0 = data.get(a, 0)
    b1 = data.get(a+1, 0)
    b2 = data.get(a+2, 0)
    b3 = data.get(a+3, 0)
    word = (b3 << 24) | (b2 << 16) | (b1 << 8) | b0
    words.append(f'{word:08x}')

with open('umem.hex', 'w') as f:
    for w in words:
        f.write(w + '\n')
    for _ in range(1024 - len(words)):
        f.write('00000000\n')
print(f'Generated umem.hex ({len(words)} words)')
