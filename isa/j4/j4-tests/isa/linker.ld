/* Linker script for j4 (SuperH-4) ISAComp tests */
/* Based on J2 test linker script */

OUTPUT_ARCH(sh)
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

  /* Exception handlers section - placed at 0x400 */
  . = 0x00000400;
  .handlers : {
    *(.handlers)
  }

  /* Vector area for VBR-relative placement */
  . = 0x00000800;
  .vectors : {
    *(.vectors)
  }

  .data : {
    *(.data)
    *(.data.*)
  }

  .bss : {
    *(.bss)
    *(.bss.*)
    *(COMMON)
  }

  /* Discard unnecessary sections */
  /DISCARD/ : {
    *(.note*)
    *(.comment)
    *(.eh_frame*)
  }
}
