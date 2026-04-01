/* ISAComp Benchmark Linker Script */
/* Starts at address 0 for ISAComp compatibility */
/* Memory: 32KB (8K words) - matches Verilog umem size */

OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
    /* 32KB unified memory starting at 0 */
    ram (rwx) : ORIGIN = 0x0, LENGTH = 32K
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

    /* Stack at top of RAM (32KB) */
    _stack = 0x8000;
}
