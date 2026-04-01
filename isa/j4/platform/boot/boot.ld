/* J4 Linux Boot Linker Script
 *
 * Memory Layout (physical addresses):
 *   0x00000000 - Boot ROM (_start) - CPU starts here
 *   0x00000100 - Device Tree Blob (_fdt) - ~1.2KB
 *   0x00001000 - Kernel .empty_zero_page (vmlinux.bin starts here)
 *   0x00002000 - Kernel entry point (_stext)
 *   _kernel_end (page-aligned) - Initramfs cpio archive
 *
 * vmlinux.bin layout (objcopy starts from lowest section at 0x80001000):
 *   vmlinux.bin[0x0000] = .empty_zero_page (virtual 0x80001000 = physical 0x1000)
 *   vmlinux.bin[0x1000] = .text _stext      (virtual 0x80002000 = physical 0x2000)
 *
 * The boot ROM sets R4 = _fdt and jumps to _kernel (P1: 0x80002000)
 * FDT is placed before the kernel so it won't be overwritten by kernel BSS
 */

OUTPUT_FORMAT("elf32-sh")
OUTPUT_ARCH(sh)
ENTRY(_start)

MEMORY
{
    /* 64MB RAM starting at 0x00000000 */
    RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 64M
}

SECTIONS
{
    /* Boot ROM at address 0 - CPU starts here */
    .text.boot 0x00000000 : {
        *(.text.boot)
    } > RAM

    /* FDT at 0x100, after boot ROM */
    .fdt 0x00000100 : {
        _fdt = .;
        KEEP(*(.fdt))
        *(.dtb)
        _fdt_end = .;
    } > RAM

    /* Kernel binary at address 0x1000
     * vmlinux.bin byte 0 = .empty_zero_page at virtual 0x80001000
     * vmlinux.bin byte 0x1000 = _stext at virtual 0x80002000
     */
    .kernel 0x00001000 : {
        KEEP(*(.kernel))
        *(.vmlinux)
    } > RAM
    _kernel_end = .;

    /* Kernel entry point at address 0x2000 */
    _kernel = 0x00002000;

    /* Initramfs cpio archive, page-aligned after kernel */
    .initramfs ALIGN(0x1000) : {
        _initramfs = .;
        KEEP(*(.initramfs))
        _initramfs_end = .;
    } > RAM
    _initramfs_size = _initramfs_end - _initramfs;

    /* BSS and other sections */
    .bss : {
        *(.bss)
        *(.sbss)
    } > RAM

    /* Symbols for size calculations */
    _ram_start = ORIGIN(RAM);
    _ram_end = ORIGIN(RAM) + LENGTH(RAM);
    _fdt_size = _fdt_end - _fdt;
    _kernel_size = _kernel_end - 0x00001000;

    /DISCARD/ : {
        *(.comment)
        *(.note*)
    }
}
