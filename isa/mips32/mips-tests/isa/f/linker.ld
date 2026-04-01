/* Linker script for MIPS32 FP tests */
MEMORY {
    TEXT (rx) : ORIGIN = 0x00000000, LENGTH = 32K
}

SECTIONS {
    . = 0x0;
    .text : { *(.text*) } > TEXT
    .data : { *(.data*) } > TEXT
    .bss : { *(.bss*) } > TEXT
    /DISCARD/ : { *(.gnu*) *(.note*) *(.comment*) *(.eh_frame*) }
}
