/* HPPA Test Linker Script */
/* Tests start at address 0x0 */

OUTPUT_ARCH( "hppa" )
ENTRY(_start)

SECTIONS
{
  /* Code starts at 0x0 */
  . = 0x0;
  .text : {
    *(.text.init)
    *(.text)
    *(.text.*)
  }
  . = ALIGN(0x100);
  .data : { *(.data) *(.data.*) }
  . = ALIGN(0x100);
  .bss : { *(.bss) *(.bss.*) }
  _end = .;

  /* Discard unwanted sections */
  /DISCARD/ : {
    *(.note.*)
    *(.comment)
    *(.gnu.*)
    *(.eh_frame)
    *(.gnu.hash)
    *(.dynsym)
    *(.dynstr)
    *(.rela.*)
    *(.dynamic)
  }
}
