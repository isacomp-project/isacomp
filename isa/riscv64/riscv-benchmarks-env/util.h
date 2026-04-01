// ISAComp Benchmark Utilities - RV64I
// Pure RV64I - no CSR instructions

#ifndef __UTIL_H
#define __UTIL_H

#include <stdint.h>
#include <stddef.h>

extern void setStats(int enable);

#define static_assert(cond) switch(0) { case 0: case !!(long)(cond): ; }

static int verify(int n, const volatile int* test, const int* verify_data)
{
  int i;
  // Unrolled for faster verification
  for (i = 0; i < n/2*2; i+=2)
  {
    int t0 = test[i], t1 = test[i+1];
    int v0 = verify_data[i], v1 = verify_data[i+1];
    if (t0 != v0) return i+1;
    if (t1 != v1) return i+2;
  }
  if (n % 2 != 0 && test[n-1] != verify_data[n-1])
    return n;
  return 0;
}

static uint64_t lfsr(uint64_t x)
{
  uint64_t bit = (x ^ (x >> 1)) & 1;
  return (x >> 1) | (bit << 62);
}

static uintptr_t insn_len(uintptr_t pc)
{
  return (*(unsigned short*)pc & 3) ? 4 : 2;
}

#define stringify_1(s) #s
#define stringify(s) stringify_1(s)

// Stats macro - no-op (no CSR counters)
#define stats(code, iter) do { \
    code; \
  } while(0)

// Memory functions declarations
void* memcpy(void* dest, const void* src, size_t len);
void* memset(void* dest, int byte, size_t len);
size_t strlen(const char *s);
size_t strnlen(const char *s, size_t n);
int strcmp(const char* s1, const char* s2);
char* strcpy(char* dest, const char* src);
long atol(const char* str);
int printf(const char* fmt, ...);
int sprintf(char* str, const char* fmt, ...);

#endif //__UTIL_H
