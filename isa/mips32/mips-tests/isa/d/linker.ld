/* Linker script for MIPS32 double-precision FP tests */
ENTRY(_start)

MEMORY
{
  RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 32K
}

SECTIONS
{
  .text : { *(.text) } > RAM
  .data : { *(.data) } > RAM
  .bss : { *(.bss) } > RAM
}
