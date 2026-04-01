/* MIPS32 Test Linker Script */
/* Uses physical addresses starting at 0x00000000 for simulation */
OUTPUT_FORMAT("elf32-tradlittlemips")
OUTPUT_ARCH(mips)
ENTRY(_start)

SECTIONS
{
    . = 0x00000000;
    .text : {
        *(.text)
        *(.text.*)
    }

    . = 0x00002000;
    .data : {
        *(.data)
        *(.data.*)
        *(.rodata)
        *(.rodata.*)
    }

    .bss : {
        *(.bss)
        *(.bss.*)
    }

    /DISCARD/ : {
        *(.note*)
        *(.comment*)
        *(.reginfo)
        *(.MIPS.abiflags)
        *(.gnu.attributes)
        *(.pdr)
        *(.mdebug*)
    }
}
