/* J2 Test Linker Script */
OUTPUT_FORMAT("elf32-shbig")
OUTPUT_ARCH(sh)
ENTRY(_start)

MEMORY
{
    ROM (rx)  : ORIGIN = 0x00000000, LENGTH = 16K
    RAM (rwx) : ORIGIN = 0x00010000, LENGTH = 48K
}

SECTIONS
{
    .text : {
        *(.text._start)
        *(.text*)
        *(.rodata*)
    } > ROM

    .vectors 0x400 : {
        *(.vectors)
    } > ROM

    .data : {
        *(.data*)
    } > RAM AT > ROM

    .bss : {
        *(.bss*)
        *(COMMON)
    } > RAM

    _end = .;
}
