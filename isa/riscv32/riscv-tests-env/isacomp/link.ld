/* ISAComp RISC-V Test Linker Script
 * Tests start at address 0x0 (not 0x80000000 like spike)
 */

OUTPUT_ARCH( "riscv" )
ENTRY(_start)

SECTIONS
{
  /* Code starts at 0x0 */
  . = 0x0;
  .text.init : { *(.text.init) }
  . = ALIGN(0x100);
  .text : { *(.text) }
  . = ALIGN(0x100);
  .data : { *(.data) }
  . = ALIGN(0x100);
  .tohost : { *(.tohost) }
  . = ALIGN(0x100);
  .bss : { *(.bss) }
  _end = .;
}
