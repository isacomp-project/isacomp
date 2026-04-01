/* Minimal init for J2 Linux boot test
 * Writes to UART and loops forever
 * Statically linked, no libc dependency
 */

/* UART TX data register address */
#define UART_TX_DATA  ((volatile unsigned int *)0x03F00104)

static void uart_putc(char c) {
    *UART_TX_DATA = c;
}

static void uart_puts(const char *s) {
    while (*s) {
        uart_putc(*s++);
    }
}

/* Syscall wrapper for write(fd, buf, count) */
static long sys_write(int fd, const void *buf, unsigned long count) {
    register long r3 __asm__("r3") = 4;  /* __NR_write */
    register long r4 __asm__("r4") = fd;
    register long r5 __asm__("r5") = (long)buf;
    register long r6 __asm__("r6") = count;
    register long r0 __asm__("r0");

    __asm__ volatile (
        "trapa #0x1f"
        : "=r"(r0)
        : "r"(r3), "r"(r4), "r"(r5), "r"(r6)
        : "memory"
    );
    return r0;
}

/* Syscall wrapper for pause() */
static void sys_pause(void) {
    register long r3 __asm__("r3") = 34;  /* __NR_pause on SuperH */
    __asm__ volatile (
        "trapa #0x1f"
        :
        : "r"(r3)
        : "memory", "r0"
    );
}

void _start(void) {
    /* Write directly to UART (bypasses kernel) */
    uart_puts("Hello from J2 userspace!\n");

    /* Also try writing through kernel - use static string to avoid memcpy */
    static const char msg[] = "Init started via syscall\n";
    sys_write(1, msg, sizeof(msg) - 1);

    /* Loop forever */
    while (1) {
        sys_pause();
    }
}
