#!/usr/bin/env python3
"""Generate a minimal initramfs cpio archive (newc format).

Creates a cpio archive containing:
  /init          - init executable
  /dev/console   - console device node (char 5,1)
  /dev/null      - null device node (char 1,3)
  /dev/kmsg      - kernel message device (char 1,11)

No root privileges needed - device nodes are created
directly in the cpio archive format.
"""

import struct
import sys
import os

def cpio_entry(name, mode, uid=0, gid=0, nlink=1, mtime=0,
               data=b'', dev_major=0, dev_minor=0, rdev_major=0, rdev_minor=0,
               ino=None):
    """Create a single cpio newc format entry."""
    if ino is None:
        ino = cpio_entry.next_ino
        cpio_entry.next_ino += 1

    namesize = len(name) + 1  # include null terminator
    filesize = len(data)

    header = "070701"  # magic
    header += "%08X" % ino
    header += "%08X" % mode
    header += "%08X" % uid
    header += "%08X" % gid
    header += "%08X" % nlink
    header += "%08X" % mtime
    header += "%08X" % filesize
    header += "%08X" % dev_major
    header += "%08X" % dev_minor
    header += "%08X" % rdev_major
    header += "%08X" % rdev_minor
    header += "%08X" % namesize
    header += "%08X" % 0  # checksum (unused in newc)

    result = header.encode('ascii')
    result += name.encode('ascii') + b'\x00'

    # Pad name+header to 4-byte boundary
    total = len(result)
    if total % 4 != 0:
        result += b'\x00' * (4 - total % 4)

    # Add file data
    result += data

    # Pad data to 4-byte boundary
    if len(data) % 4 != 0:
        result += b'\x00' * (4 - len(data) % 4)

    return result

cpio_entry.next_ino = 1


def main():
    if len(sys.argv) < 3:
        print("Usage: gen_initramfs.py <init_binary> <output.cpio>")
        sys.exit(1)

    init_binary = sys.argv[1]
    output_cpio = sys.argv[2]

    # Read init binary
    with open(init_binary, 'rb') as f:
        init_data = f.read()

    archive = b''

    # Root directory
    archive += cpio_entry(".", mode=0o40755, nlink=3)

    # /dev directory
    archive += cpio_entry("dev", mode=0o40755, nlink=2)

    # /dev/console - character device 5,1
    archive += cpio_entry("dev/console", mode=0o20600,
                          rdev_major=5, rdev_minor=1)

    # /dev/null - character device 1,3
    archive += cpio_entry("dev/null", mode=0o20666,
                          rdev_major=1, rdev_minor=3)

    # /dev/kmsg - character device 1,11
    # Used by init to write messages via printk (goes to earlycon)
    archive += cpio_entry("dev/kmsg", mode=0o20600,
                          rdev_major=1, rdev_minor=11)

    # /init - executable
    archive += cpio_entry("init", mode=0o100755, data=init_data)

    # Trailer
    archive += cpio_entry("TRAILER!!!", mode=0, ino=0)

    # Pad archive to 512-byte boundary (optional but conventional)
    if len(archive) % 512 != 0:
        archive += b'\x00' * (512 - len(archive) % 512)

    with open(output_cpio, 'wb') as f:
        f.write(archive)

    print(f"Created {output_cpio}: {len(archive)} bytes")
    print(f"  init binary: {len(init_data)} bytes")


if __name__ == '__main__':
    main()
