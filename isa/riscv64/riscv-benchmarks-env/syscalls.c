// ISAComp Benchmark Syscalls - RV64I
// Pure RV64I - no CSR instructions

#include <stdint.h>
#include <stdarg.h>
#include <limits.h>

#include "util.h"

extern volatile uint64_t tohost;
extern volatile uint64_t fromhost;

// Pass/fail functions defined in crt.S
extern void pass(void) __attribute__((noreturn));
extern void fail(void) __attribute__((noreturn));

void setStats(int enable)
{
  // No CSR counters available
}

void __attribute__((noreturn)) tohost_exit(uintptr_t code)
{
  if (code == 0) {
    pass();
  } else {
    fail();
  }
  while (1);
}

uintptr_t __attribute__((weak)) handle_trap(uintptr_t cause, uintptr_t epc, uintptr_t regs[32])
{
  // Default trap handler - fail
  tohost_exit(1337);
}

void exit(int code)
{
  tohost_exit(code);
}

void abort()
{
  exit(128 + 6);  // SIGABRT = 6
}

// Simplified print function - does nothing in simulation
// (we verify correctness via return value, not output)
void printstr(const char* s)
{
  // No-op in ISAComp simulation
}

void __attribute__((weak)) thread_entry(int cid, int nc)
{
  // Single-threaded only
  while (cid != 0);
}

// Simplified printf - does nothing
int printf(const char* fmt, ...)
{
  // No-op in ISAComp simulation
  return 0;
}

int sprintf(char* str, const char* fmt, ...)
{
  // Minimal implementation
  str[0] = 0;
  return 0;
}

void printhex(uint64_t x)
{
  // No-op
}

// Memory functions
void* memcpy(void* dest, const void* src, size_t len)
{
  const char* s = src;
  char *d = dest;
  while (len-- > 0)
    *d++ = *s++;
  return dest;
}

void* memset(void* dest, int byte, size_t len)
{
  char *d = dest;
  while (len-- > 0)
    *d++ = byte;
  return dest;
}

size_t strlen(const char *s)
{
  const char *p = s;
  while (*p)
    p++;
  return p - s;
}

size_t strnlen(const char *s, size_t n)
{
  const char *p = s;
  while (n-- && *p)
    p++;
  return p - s;
}

int strcmp(const char* s1, const char* s2)
{
  unsigned char c1, c2;

  do {
    c1 = *s1++;
    c2 = *s2++;
  } while (c1 != 0 && c1 == c2);

  return c1 - c2;
}

char* strcpy(char* dest, const char* src)
{
  char* d = dest;
  while ((*d++ = *src++))
    ;
  return dest;
}

long atol(const char* str)
{
  long res = 0;
  int sign = 0;

  while (*str == ' ')
    str++;

  if (*str == '-' || *str == '+') {
    sign = *str == '-';
    str++;
  }

  while (*str) {
    res *= 10;
    res += *str++ - '0';
  }

  return sign ? -res : res;
}
