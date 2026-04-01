/* Minimal init for M68K Linux boot test
 * Writes to console via syscall and loops forever
 * Statically linked, no libc dependency
 *
 * M68K Linux syscall convention:
 *   Syscall number in D0
 *   Arguments in D1, D2, D3, D4, D5
 *   Return value in D0
 *   Invoked via trap #0
 */

/* Syscall wrapper for write(fd, buf, count) */
static long sys_write(int fd, const void *buf, unsigned long count) {
    register long d0 __asm__("d0") = 4;  /* __NR_write */
    register long d1 __asm__("d1") = fd;
    register long d2 __asm__("d2") = (long)buf;
    register long d3 __asm__("d3") = count;

    __asm__ volatile (
        "trap #0"
        : "+r"(d0)
        : "r"(d1), "r"(d2), "r"(d3)
        : "memory"
    );
    return d0;
}

/* Syscall wrapper for pause() */
static void sys_pause(void) {
    register long d0 __asm__("d0") = 29;  /* __NR_pause */
    __asm__ volatile (
        "trap #0"
        : "+r"(d0)
        :
        : "memory"
    );
}

void _start(void) {
    static const char msg[] = "Hello from M68K userspace!\n";
    sys_write(1, msg, sizeof(msg) - 1);

    /* Loop forever */
    while (1) {
        sys_pause();
    }
}
