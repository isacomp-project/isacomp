/* Minimal linker script for M68K init */
ENTRY(_start)

SECTIONS {
    . = 0x1000;
    .text : { *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.*) }
    .bss : { *(.bss .bss.* COMMON) }
    /DISCARD/ : { *(.comment) *(.note.*) *(.eh_frame) }
}
