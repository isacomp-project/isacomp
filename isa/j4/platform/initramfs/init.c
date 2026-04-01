/* Minimal init for J4 (SH4) Linux boot test
 * Writes to console via syscall and loops forever
 * Statically linked, no libc dependency
 *
 * SH4 Linux syscall convention:
 *   Syscall number in R3
 *   Arguments in R4, R5, R6, R7
 *   Return value in R0
 *   Invoked via trapa #0x15
 */

/* Syscall wrapper for write(fd, buf, count) */
static long sys_write(int fd, const void *buf, unsigned long count) {
    register long r3 __asm__("r3") = 4;  /* __NR_write */
    register long r4 __asm__("r4") = fd;
    register long r5 __asm__("r5") = (long)buf;
    register long r6 __asm__("r6") = count;
    register long r0 __asm__("r0");

    __asm__ volatile (
        "trapa #0x15"
        : "=r"(r0)
        : "r"(r3), "r"(r4), "r"(r5), "r"(r6)
        : "memory"
    );
    return r0;
}

/* Syscall wrapper for pause() */
static void sys_pause(void) {
    register long r3 __asm__("r3") = 29;  /* __NR_pause */
    __asm__ volatile (
        "trapa #0x15"
        :
        : "r"(r3)
        : "memory", "r0"
    );
}

void _start(void) {
    static const char msg[] = "Hello from J4 userspace!\n";
    sys_write(1, msg, sizeof(msg) - 1);

    /* Loop forever */
    while (1) {
        sys_pause();
    }
}
