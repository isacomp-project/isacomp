/* Minimal init for OpenPOWER Linux boot test
 * Writes to console via syscall and loops forever
 * Statically linked, no libc dependency
 *
 * PowerPC64 Linux syscall convention:
 *   Syscall number in r0
 *   Arguments in r3, r4, r5, r6, r7, r8
 *   Return value in r3
 *   CR0.SO set on error
 *   Invoked via 'sc' instruction
 */

/* PowerPC64 syscall numbers */
#define __NR_write  4
#define __NR_openat 286
#define __NR_close  6
#define __NR_pause  29

/* Syscall wrapper for write(fd, buf, count) */
static long sys_write(int fd, const void *buf, unsigned long count) {
    register long r0 __asm__("r0") = __NR_write;
    register long r3 __asm__("r3") = fd;
    register long r4 __asm__("r4") = (long)buf;
    register long r5 __asm__("r5") = count;

    __asm__ volatile (
        "sc"
        : "+r"(r3), "+r"(r4), "+r"(r5)
        : "r"(r0)
        : "memory", "cr0", "r6", "r7", "r8",
          "r9", "r10", "r11", "r12"
    );
    return r3;
}

/* Syscall wrapper for openat(dirfd, pathname, flags, mode) */
static long sys_openat(int dirfd, const char *pathname, int flags, int mode) {
    register long r0 __asm__("r0") = __NR_openat;
    register long r3 __asm__("r3") = dirfd;
    register long r4 __asm__("r4") = (long)pathname;
    register long r5 __asm__("r5") = flags;
    register long r6 __asm__("r6") = mode;

    __asm__ volatile (
        "sc"
        : "+r"(r3), "+r"(r4), "+r"(r5), "+r"(r6)
        : "r"(r0)
        : "memory", "cr0", "r7", "r8",
          "r9", "r10", "r11", "r12"
    );
    return r3;
}

/* Syscall wrapper for close(fd) */
static long sys_close(int fd) {
    register long r0 __asm__("r0") = __NR_close;
    register long r3 __asm__("r3") = fd;

    __asm__ volatile (
        "sc"
        : "+r"(r3)
        : "r"(r0)
        : "memory", "cr0", "r4", "r5", "r6", "r7", "r8",
          "r9", "r10", "r11", "r12"
    );
    return r3;
}

/* Syscall wrapper for pause() */
static void sys_pause(void) {
    register long r0 __asm__("r0") = __NR_pause;
    register long r3 __asm__("r3");

    __asm__ volatile (
        "sc"
        : "=r"(r3)
        : "r"(r0)
        : "memory", "cr0", "r4", "r5", "r6", "r7", "r8",
          "r9", "r10", "r11", "r12"
    );
}

void _start(void) {
    static const char msg[] = "Hello from OpenPOWER userspace!\n";
    static const char kmsg_path[] = "/dev/kmsg";

    /* Write to stdout (fd 1) */
    sys_write(1, msg, sizeof(msg) - 1);

    /* Also write via /dev/kmsg for guaranteed console output */
    long fd = sys_openat(-100, kmsg_path, 1 /* O_WRONLY */, 0);
    if (fd >= 0) {
        sys_write(fd, msg, sizeof(msg) - 1);
        sys_close(fd);
    }

    /* Loop forever */
    while (1) {
        sys_pause();
    }
}
