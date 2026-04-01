/* Linker script for SPARCv8 ISAComp tests */
/* Based on MIPS32 and J2 test linker scripts */

OUTPUT_ARCH(sparc)
ENTRY(_start)

SECTIONS
{
  /* Start at address 0 for ISAComp */
  . = 0x00000000;

  .text : {
    *(.text)
    *(.text.*)
  }

  .rodata : {
    *(.rodata)
    *(.rodata.*)
  }

  /* Trap table - SPARCv8 uses TBR (Trap Base Register) */
  /* Place trap handlers at 0x1000 */
  . = 0x00001000;
  .trap : {
    *(.trap)
    *(.trap.*)
  }

  /* Data section */
  . = 0x00002000;
  .data : {
    *(.data)
    *(.data.*)
  }

  .bss : {
    *(.bss)
    *(.bss.*)
    *(COMMON)
  }

  /* Stack - grows downward from 0x10000 */
  . = 0x00010000;
  .stack : {
    _stack_top = .;
  }

  /* Discard unnecessary sections */
  /DISCARD/ : {
    *(.note*)
    *(.comment)
    *(.eh_frame*)
  }
}
