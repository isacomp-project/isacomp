/*
 * Alpha Test Linker Script
 * For bare-metal execution on generated processor
 */

OUTPUT_FORMAT("elf64-alpha")
OUTPUT_ARCH(alpha)
ENTRY(_start)

MEMORY
{
    /* Code starts at 0x0 */
    ROM (rx)  : ORIGIN = 0x00000000, LENGTH = 64K
    /* Data at 0x10000 */
    RAM (rwx) : ORIGIN = 0x00010000, LENGTH = 64K
}

SECTIONS
{
    . = 0x0;

    .text : {
        *(.text.init)
        *(.text)
        *(.text.*)
    } > ROM

    . = ALIGN(8);

    .rodata : {
        *(.rodata)
        *(.rodata.*)
    } > ROM

    . = 0x10000;

    .data : {
        *(.data)
        *(.data.*)
        *(.sdata)
        *(.sdata.*)
    } > RAM

    .bss : {
        *(.bss)
        *(.bss.*)
        *(.sbss)
        *(.sbss.*)
    } > RAM

    . = ALIGN(8);

    /* Stack at end of RAM */
    _stack = 0x1FFF8;

    /* Symbols for tohost/fromhost communication */
    .tohost : {
        *(.tohost)
    } > RAM
}
