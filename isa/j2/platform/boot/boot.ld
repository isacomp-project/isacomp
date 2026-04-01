/* J2 Linux Boot Linker Script
 *
 * Memory Layout:
 *   0x00000000 - Boot ROM (_start) - CPU starts here
 *   0x00000100 - Device Tree Blob (_fdt) - ~1.2KB
 *   0x00001000 - Kernel binary start (vmlinux.bin loaded here)
 *   0x00002000 - Kernel entry point (_stext)
 *
 * The boot ROM sets R4 = _fdt and jumps to _kernel (0x2000)
 * FDT is placed before the kernel so it won't be overwritten by kernel BSS
 */

OUTPUT_FORMAT("elf32-shbig-linux")
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

    /* Kernel binary at address 0x1000 */
    /* vmlinux.bin first byte corresponds to kernel address 0x1000 */
    /* Entry point (_stext) is at 0x2000 */
    /* Note: Initramfs is embedded in kernel via CONFIG_INITRAMFS_SOURCE */
    .kernel 0x00001000 : {
        /* Linux kernel binary (includes embedded initramfs) */
        KEEP(*(.kernel))
        *(.vmlinux)
    } > RAM
    _kernel_end = .;

    /* Kernel entry point at address 0x2000 */
    _kernel = 0x00002000;

    /* BSS and other sections */
    .bss : {
        *(.bss)
        *(.sbss)
    } > RAM

    /* Padding section (not used but keep for compatibility) */
    .padding : {
        *(.padding)
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
