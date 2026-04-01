/*
 * Minimal /init for RISC-V 32 initramfs
 * Prints "Hello from RISC-V userspace!" and loops
 */
#include <stdio.h>
#include <unistd.h>

int main(void)
{
	printf("Hello from RISC-V userspace!\n");
	fflush(stdout);
	/* Spin forever */
	for (;;)
		usleep(1000000);
	return 0;
}
