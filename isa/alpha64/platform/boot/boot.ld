/* Alpha64 Boot Linker Script
 *
 * Memory layout:
 *   0x00000000 - PALcode entry point
 *   0x00008000 - Boot ROM (HWRPB builder + kernel launcher)
 *   0x01000000 - Kernel image (loaded separately)
 */

OUTPUT_FORMAT("elf64-alpha")
ENTRY(pal_reset)

SECTIONS
{
    /* PALcode at address 0 */
    . = 0x0;
    .palcode : { palcode.o(.text) }

    /* Boot ROM at 0x8000 */
    . = 0x8000;
    .bootrom : { bootrom.o(.text) bootrom.o(.data) bootrom.o(.rodata) }

    /* Kernel image at 16MB (loaded from separate binary, optional) */
    . = 0x01000000;
    .kernel : { KEEP(*kernel*(.data)) }

    /DISCARD/ : { *(.note*) *(.comment*) *(.eh_frame*) }
}
