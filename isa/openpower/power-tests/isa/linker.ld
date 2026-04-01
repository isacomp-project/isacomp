/* OpenPOWER Test Linker Script */
/* Memory layout matching openpower_sfs processor */
/* Little-endian PowerPC64 */

OUTPUT_FORMAT("elf64-powerpcle")
OUTPUT_ARCH(powerpc:common64)
ENTRY(_start)

SECTIONS
{
    . = 0x0;

    .text : {
        *(.text)
        *(.text.*)
    }

    . = ALIGN(8);

    .rodata : {
        *(.rodata)
        *(.rodata.*)
    }

    . = 0x10000;

    .data : {
        *(.data)
        *(.data.*)
        *(.sdata)
        *(.sdata.*)
    }

    .bss : {
        *(.bss)
        *(.bss.*)
        *(.sbss)
        *(.sbss.*)
    }

    /DISCARD/ : {
        *(.comment)
        *(.note.*)
        *(.eh_frame)
        *(.eh_frame_hdr)
        *(.dynsym)
        *(.dynstr)
        *(.dynamic)
        *(.gnu.hash)
        *(.rela.*)
    }
}
