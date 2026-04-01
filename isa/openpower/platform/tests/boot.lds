/* OpenPOWER ISAComp Test Boot Linker Script */
/* Big-endian 64-bit PowerPC, flat binary */

OUTPUT_FORMAT("elf64-powerpc", "elf64-powerpc", "elf64-powerpc")
OUTPUT_ARCH(powerpc:common64)
ENTRY(_start)

PHDRS
{
    text PT_LOAD;
}

SECTIONS
{
    . = 0x00000000;

    .text : {
        *(.text.boot)
        *(.text)
    } :text

    .rodata : {
        *(.rodata)
        *(.rodata.*)
    } :text

    .data : {
        *(.data)
    } :text

    .bss : {
        *(.bss)
    } :text

    /* Stack at 1MB */
    . = 0x00100000;
    _stack_top = .;
}
