/* M68K Linux Boot Image Linker Script
 *
 * Memory Layout:
 *   0x00000000 - 0x000003FF: Exception vectors (1KB)
 *   0x00000400 - 0x000004FF: Boot ROM code
 *   0x00000500 - 0x000007FF: Bootinfo records
 *   0x00001000 - .........: Linux kernel (_stext)
 *
 * The boot ROM initializes the processor, sets A0 to point to
 * bootinfo records, then jumps to the kernel at _stext (0x1000).
 */

OUTPUT_FORMAT("elf32-m68k", "elf32-m68k", "elf32-m68k")
OUTPUT_ARCH(m68k)
ENTRY(_vectors)

MEMORY
{
    VECTORS  (rx)  : ORIGIN = 0x00000000, LENGTH = 0x400
    BOOTROM  (rx)  : ORIGIN = 0x00000400, LENGTH = 0x100
    BOOTINFO (r)   : ORIGIN = 0x00000500, LENGTH = 0xB00
    KERNEL   (rx)  : ORIGIN = 0x00001000, LENGTH = 64M - 4K
}

SECTIONS
{
    /* Exception Vector Table - must be at address 0 */
    .vectors :
    {
        *(.vectors)
    } > VECTORS

    /* Boot ROM code */
    .text.boot :
    {
        *(.text.boot)
        *(.text)
    } > BOOTROM

    /* Bootinfo records */
    .bootinfo :
    {
        *(.bootinfo)
        *(.rodata*)
    } > BOOTINFO

    /* Discard unnecessary sections */
    /DISCARD/ :
    {
        *(.comment)
        *(.note*)
    }
}
