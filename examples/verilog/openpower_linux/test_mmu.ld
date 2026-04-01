OUTPUT_FORMAT("elf64-powerpc", "elf64-powerpc", "elf64-powerpc")
OUTPUT_ARCH(powerpc:common64)
ENTRY(_start)
SECTIONS
{
    . = 0x0;
    .text : { *(.text) }
    /DISCARD/ : { *(*) }
}
