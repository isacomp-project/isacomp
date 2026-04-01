/*
 * linux/arch/alpha/kernel/sys_isacomp.c
 *
 * ISAComp Alpha64 Platform support
 *
 * Custom platform for ISAComp-generated single-cycle Alpha64 processor.
 * Simple memory-mapped peripherals: interrupt controller, timer, UART.
 * No PCI bus, no chipset (no Tsunami/CIA/LCA/etc).
 */

#include <linux/kernel.h>
#include <linux/types.h>
#include <linux/init.h>
#include <linux/irq.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/console.h>
#include <linux/serial_8250.h>
#include <linux/serial_core.h>

#include <asm/hwrpb.h>
#include <asm/irq.h>
#include <asm/mmu_context.h>
#include <asm/tlbflush.h>

#include "irq_impl.h"
#include "machvec_impl.h"
#include "isacomp.h"

/*
 * I/O operations
 *
 * ISAComp has no legacy I/O port space or PCI bus. All I/O is memory-mapped.
 * The machine vector I/O functions provide direct KSEG-based access:
 *   - ioportmap: maps legacy I/O ports into KSEG (peripheral PA space)
 *   - ioread/iowrite: direct memory load/store at the mapped address
 *   - read/write: same, for MMIO addresses returned by ioremap
 *
 * I/O port addresses are mapped to PA 0x80000000 + port, placing them
 * in the peripheral region. Probes of non-existent legacy ports (like
 * the PIT or ISA DMA) will read 0 from unused addresses, causing
 * drivers to detect no hardware and move on.
 */

#define ISACOMP_KSEG_BASE  0xFFFFFC0000000000UL
#define ISACOMP_IO_BASE    0x80000000UL  /* Peripheral PA space */

static void __iomem *
isacomp_ioportmap(unsigned long port)
{
	return (void __iomem *)(ISACOMP_KSEG_BASE + ISACOMP_IO_BASE + port);
}

static void __iomem *
isacomp_ioremap(unsigned long phys, unsigned long size)
{
	return (void __iomem *)(ISACOMP_KSEG_BASE + phys);
}

static void
isacomp_iounmap(volatile void __iomem *addr)
{
	/* Nothing to do for KSEG mappings */
}

static int
isacomp_is_ioaddr(unsigned long addr)
{
	return 1;  /* All addresses are accessible via KSEG */
}

static int
isacomp_is_mmio(const volatile void __iomem *addr)
{
	return 1;
}

static u8 isacomp_ioread8(const void __iomem *a)
{
	return *(const volatile u8 __force *)a;
}

static u16 isacomp_ioread16(const void __iomem *a)
{
	return *(const volatile u16 __force *)a;
}

static u32 isacomp_ioread32(const void __iomem *a)
{
	return *(const volatile u32 __force *)a;
}

static u64 isacomp_ioread64(const void __iomem *a)
{
	return *(const volatile u64 __force *)a;
}

static void isacomp_iowrite8(u8 b, void __iomem *a)
{
	*(volatile u8 __force *)a = b;
}

static void isacomp_iowrite16(u16 b, void __iomem *a)
{
	*(volatile u16 __force *)a = b;
}

static void isacomp_iowrite32(u32 b, void __iomem *a)
{
	*(volatile u32 __force *)a = b;
}

static void isacomp_iowrite64(u64 b, void __iomem *a)
{
	*(volatile u64 __force *)a = b;
}

static u8 isacomp_readb(const volatile void __iomem *a)
{
	return *(const volatile u8 __force *)a;
}

static u16 isacomp_readw(const volatile void __iomem *a)
{
	return *(const volatile u16 __force *)a;
}

static u32 isacomp_readl(const volatile void __iomem *a)
{
	return *(const volatile u32 __force *)a;
}

static u64 isacomp_readq(const volatile void __iomem *a)
{
	return *(const volatile u64 __force *)a;
}

static void isacomp_writeb(u8 b, volatile void __iomem *a)
{
	*(volatile u8 __force *)a = b;
}

static void isacomp_writew(u16 b, volatile void __iomem *a)
{
	*(volatile u16 __force *)a = b;
}

static void isacomp_writel(u32 b, volatile void __iomem *a)
{
	*(volatile u32 __force *)a = b;
}

static void isacomp_writeq(u64 b, volatile void __iomem *a)
{
	*(volatile u64 __force *)a = b;
}

/* Memory-mapped register access via KSEG */
static inline u64 intc_read(unsigned long offset)
{
    return *(volatile u64 *)(ISACOMP_INTC_VADDR + offset);
}

static inline void intc_write(unsigned long offset, u64 val)
{
    *(volatile u64 *)(ISACOMP_INTC_VADDR + offset) = val;
}

static inline u64 timer_read(unsigned long offset)
{
    return *(volatile u64 *)(ISACOMP_TIMER_VADDR + offset);
}

static inline void timer_write(unsigned long offset, u64 val)
{
    *(volatile u64 *)(ISACOMP_TIMER_VADDR + offset) = val;
}

/*
 * Interrupt handling
 */

static void isacomp_enable_irq(struct irq_data *d)
{
    unsigned long mask = intc_read(INTC_IRQ_ENABLE);
    mask |= (1UL << d->irq);
    intc_write(INTC_IRQ_ENABLE, mask);
}

static void isacomp_disable_irq(struct irq_data *d)
{
    unsigned long mask = intc_read(INTC_IRQ_ENABLE);
    mask &= ~(1UL << d->irq);
    intc_write(INTC_IRQ_ENABLE, mask);
}

static struct irq_chip isacomp_irq_chip = {
    .name           = "ISAComp",
    .irq_enable     = isacomp_enable_irq,
    .irq_disable    = isacomp_disable_irq,
    .irq_mask       = isacomp_disable_irq,
    .irq_unmask     = isacomp_enable_irq,
};

static void __init
isacomp_init_irq(void)
{
    int i;

    /* Initialize all IRQs with our chip */
    for (i = 0; i < ISACOMP_NR_IRQS; i++) {
        irq_set_chip_and_handler(i, &isacomp_irq_chip, handle_level_irq);
        irq_set_status_flags(i, IRQ_LEVEL);
    }

    /* Enable timer and UART interrupts */
    intc_write(INTC_IRQ_ENABLE, (1UL << ISACOMP_IRQ_TIMER) | (1UL << ISACOMP_IRQ_UART));

    /* No ISA DMA on this platform - skip common_init_isa_dma() which
     * accesses I/O ports 0x00-0x0F that don't exist on ISAComp. */
}

static void
isacomp_device_interrupt(unsigned long vector)
{
    unsigned long pending;
    int irq;

    /* Read pending (masked) interrupts from controller */
    pending = intc_read(INTC_IRQ_PENDING);

    while (pending) {
        irq = __ffs(pending);  /* Find first set bit */
        handle_irq(irq);
        pending &= ~(1UL << irq);
    }
}

/*
 * Timer setup
 */

static void __init
isacomp_init_timer(void)
{
    /* Set timer period for desired HZ */
    timer_write(TIMER_PERIOD, ISACOMP_TIMER_DEFAULT_PERIOD);

    /* Clear any pending interrupt */
    timer_write(TIMER_STATUS, 1);

    /* Enable timer */
    timer_write(TIMER_CTL, 1);
}

/*
 * RTC initialization - called from time_init() via machine vector.
 * Programs our memory-mapped timer and installs the timer interrupt
 * handler on RTC_IRQ (IRQ 8), which is where the kernel routes
 * PALcode clock interrupts (entInt type 1).
 */
static void __init
isacomp_init_rtc(void)
{
    /* Program the hardware timer */
    isacomp_init_timer();

    /* Install rtc_timer_interrupt on RTC_IRQ=8.
     * NULL handler => defaults to rtc_timer_interrupt.
     * PALcode delivers timer as entInt(a0=1) -> handle_irq(RTC_IRQ). */
    init_rtc_irq(NULL);
}

/*
 * Early boot console - writes directly to UART MMIO
 * Registered in init_arch so panic messages are visible in simulation.
 */
static void isacomp_console_write(struct console *co, const char *s,
                                  unsigned int n)
{
    volatile u64 *uart_thr = (volatile u64 *)ISACOMP_UART_VADDR;
    while (n--)
        *uart_thr = (u64)(unsigned char)*s++;
}

static struct console isacomp_early_console = {
    .name   = "isacomp",
    .write  = isacomp_console_write,
    .flags  = CON_PRINTBUFFER | CON_BOOT,
    .index  = -1,
};

/*
 * Platform initialization
 */

/*
 * Set est_cycle_freq before time_init() to skip PIT/CMOS calibration.
 * time_init() calls calibrate_cc_with_pit() which accesses I/O ports
 * 0x40-0x43 (PIT timer) that don't exist on ISAComp. Setting this
 * variable bypasses the calibration entirely.
 */
extern unsigned long est_cycle_freq;

static void __init
isacomp_init_arch(void)
{
    struct uart_port uart_port;

    /* Direct UART test - write "ISAComp\n" to verify write path */
    volatile u64 *uart = (volatile u64 *)ISACOMP_UART_VADDR;
    const char *msg = "ISAComp boot\n";
    while (*msg)
        *uart = (u64)(unsigned char)*msg++;

    register_console(&isacomp_early_console);

    /* Register UART as memory-mapped 8250 port on ttyS0.
     * Without this, the 8250 driver uses UPIO_PORT with inb/outb to the
     * standard COM1 address (0x3f8).  ioportmap maps that to PA 0x800003f8
     * which doesn't hit our UART at PA 0x80020000.  Each wait_for_xmitr
     * call then times out (10000 * __delay iterations) instead of seeing
     * THRE=1 immediately from the real UART LSR. */
    memset(&uart_port, 0, sizeof(uart_port));
    uart_port.membase  = (void __iomem *)ISACOMP_UART_VADDR;
    uart_port.mapbase  = ISACOMP_UART_BASE;
    uart_port.irq      = ISACOMP_IRQ_UART;
    uart_port.uartclk  = 1843200;
    uart_port.iotype   = UPIO_MEM;
    uart_port.regshift = 3;
    uart_port.flags    = UPF_BOOT_AUTOCONF | UPF_SKIP_TEST | UPF_FIXED_TYPE;
    uart_port.type     = PORT_16550A;
    uart_port.line     = 0;
    early_serial_setup(&uart_port);

    /* Pre-set cycle frequency to skip PIT/CMOS calibration in time_init().
     * Without this, time_init() tries to access ISA PIT (ports 0x40-43)
     * and CMOS RTC (ports 0x70-71), which don't exist on ISAComp. */
    est_cycle_freq = ISACOMP_CLOCK_FREQ;
}

static void
isacomp_kill_arch(int mode)
{
    /* Halt: disable interrupts and loop */
    /* In simulation, this will eventually hit the timeout */
    local_irq_disable();
    while (1)
        ;
}

/*
 * Dummy HAE register - ISAComp has no PCI/HAE hardware, but the kernel's
 * setup_arch dereferences hae_register. Provide a dummy to avoid NULL deref.
 */
static unsigned long isacomp_hae_dummy;

/*
 * Machine Vector
 *
 * This is the central dispatch table for platform-specific operations.
 * The kernel selects this based on HWRPB sys_type matching ST_ISACOMP.
 */

struct alpha_machine_vector isacomp_mv __initmv = {
    .vector_name        = "ISAComp",
    .nr_irqs            = ISACOMP_NR_IRQS,
    .rtc_port           = 0,              /* No RTC */
    .hae_cache          = 0,
    .hae_register       = &isacomp_hae_dummy,

    /* I/O port and MMIO operations */
    .mv_ioread8         = isacomp_ioread8,
    .mv_ioread16        = isacomp_ioread16,
    .mv_ioread32        = isacomp_ioread32,
    .mv_ioread64        = isacomp_ioread64,
    .mv_iowrite8        = isacomp_iowrite8,
    .mv_iowrite16       = isacomp_iowrite16,
    .mv_iowrite32       = isacomp_iowrite32,
    .mv_iowrite64       = isacomp_iowrite64,
    .mv_readb           = isacomp_readb,
    .mv_readw           = isacomp_readw,
    .mv_readl           = isacomp_readl,
    .mv_readq           = isacomp_readq,
    .mv_writeb          = isacomp_writeb,
    .mv_writew          = isacomp_writew,
    .mv_writel          = isacomp_writel,
    .mv_writeq          = isacomp_writeq,
    .mv_ioportmap       = isacomp_ioportmap,
    .mv_ioremap         = isacomp_ioremap,
    .mv_iounmap         = isacomp_iounmap,
    .mv_is_ioaddr       = isacomp_is_ioaddr,
    .mv_is_mmio         = isacomp_is_mmio,

    /* EV5 MMU operations (EV56 uses EV5 TLB management) */
    .max_asn            = EV5_MAX_ASN,
    .mv_switch_mm       = ev5_switch_mm,
    .mv_activate_mm     = ev5_activate_mm,
    .mv_flush_tlb_current      = ev5_flush_tlb_current,
    .mv_flush_tlb_current_page = ev5_flush_tlb_current_page,

    .init_arch          = isacomp_init_arch,
    .init_irq           = isacomp_init_irq,
    .init_rtc           = isacomp_init_rtc,
    .init_pci           = NULL,           /* No PCI */
    .kill_arch          = isacomp_kill_arch,

    .device_interrupt   = isacomp_device_interrupt,
};
ALIAS_MV(isacomp)
