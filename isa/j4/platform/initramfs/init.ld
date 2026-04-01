/* Linker script for SH4 Linux user-space init binary */
OUTPUT_FORMAT("elf32-sh", "elf32-sh", "elf32-sh")
OUTPUT_ARCH(sh)
ENTRY(_start)

SECTIONS
{
    /* Standard Linux user-space base address */
    . = 0x00400000;

    .text : ALIGN(0x1000) {
        *(.text .text.*)
    }

    .rodata : ALIGN(4) {
        *(.rodata .rodata.*)
    }

    .data : ALIGN(0x1000) {
        *(.data .data.*)
    }

    .bss : ALIGN(4) {
        *(.bss .bss.*)
        *(COMMON)
    }

    /DISCARD/ : {
        *(.stack)
        *(.comment)
        *(.note.GNU-stack)
    }
}
