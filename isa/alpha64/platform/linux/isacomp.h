/* ISAComp Alpha64 Platform Definitions
 *
 * Custom platform for ISAComp-generated Alpha64 processor.
 * No PCI, no Tsunami, no CIA -- just simple memory-mapped peripherals.
 */

#ifndef _ALPHA_ISACOMP_H
#define _ALPHA_ISACOMP_H

/* System type (matches HWRPB sys_type field) */
#define ST_ISACOMP          100

/* Peripheral base addresses (physical) */
#define ISACOMP_INTC_BASE   0x80000000UL
#define ISACOMP_TIMER_BASE  0x80010000UL
#define ISACOMP_UART_BASE   0x80020000UL

/* KSEG mapping: VA = 0xFFFFFC0000000000 + PA */
#define ISACOMP_INTC_VADDR  (0xFFFFFC0000000000UL + ISACOMP_INTC_BASE)
#define ISACOMP_TIMER_VADDR (0xFFFFFC0000000000UL + ISACOMP_TIMER_BASE)
#define ISACOMP_UART_VADDR  (0xFFFFFC0000000000UL + ISACOMP_UART_BASE)

/* Interrupt controller registers (8-byte aligned) */
#define INTC_IRQ_STATUS     0x00
#define INTC_IRQ_ENABLE     0x08
#define INTC_IRQ_PENDING    0x10

/* Timer registers (8-byte aligned) */
#define TIMER_CTL           0x00
#define TIMER_PERIOD        0x08
#define TIMER_COUNT         0x10
#define TIMER_STATUS        0x18

/* Timer defaults */
#define ISACOMP_CLOCK_FREQ  50000000    /* 50 MHz */
#define ISACOMP_TIMER_FREQ  1024        /* HZ = 1024 */
#define ISACOMP_TIMER_DEFAULT_PERIOD (ISACOMP_CLOCK_FREQ / ISACOMP_TIMER_FREQ)

/* IRQ numbers (index into irq_sources) */
#define ISACOMP_IRQ_TIMER   0
#define ISACOMP_IRQ_UART    1
#define ISACOMP_NR_IRQS     16

/* ISR bit positions for device interrupts */
/* Device IRQs map to ISR bits 4+ (bits 0-3 are software/reserved) */
#define ISACOMP_ISR_TIMER   (1UL << 4)
#define ISACOMP_ISR_UART    (1UL << 5)

#endif /* _ALPHA_ISACOMP_H */
