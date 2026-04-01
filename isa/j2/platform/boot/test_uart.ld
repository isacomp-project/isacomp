/* Simple linker script for UART test */

OUTPUT_FORMAT("elf32-sh")
OUTPUT_ARCH(sh)
ENTRY(_start)

SECTIONS
{
    /* Place code at 0x0000 */
    .text 0x00000000 : {
        *(.text.boot)
        *(.text)
    }

    /DISCARD/ : {
        *(.comment)
        *(.note*)
    }
}
