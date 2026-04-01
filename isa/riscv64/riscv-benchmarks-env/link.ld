/* ISAComp Benchmark Linker Script - RV64I */
/* Starts at address 0 for ISAComp compatibility */
/* Memory: 64KB (8K doublewords) */

OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
    /* 64KB unified memory starting at 0 */
    ram (rwx) : ORIGIN = 0x0, LENGTH = 64K
}

SECTIONS
{
    /* Code starts at 0 */
    . = 0x0;

    .text : {
        *(.text.init)
        *(.text*)
    } > ram

    .rodata : {
        *(.rodata*)
    } > ram

    .data : {
        . = ALIGN(8);
        *(.sdata*)
        *(.data*)
    } > ram

    .bss : {
        . = ALIGN(8);
        __bss_start = .;
        *(.sbss*)
        *(.bss*)
        *(COMMON)
        __bss_end = .;
    } > ram

    . = ALIGN(8);
    __global_pointer$ = . + 0x800;
    _end = .;

    /* Stack at top of RAM (64KB) */
    _stack = 0x10000;
}
