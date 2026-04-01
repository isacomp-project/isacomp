// Minimal string.h for ISAComp RV64I benchmarks

#ifndef _STRING_H
#define _STRING_H

#include <stddef.h>

// Provided by syscalls.c
void* memcpy(void* dest, const void* src, size_t len);
void* memset(void* dest, int byte, size_t len);
size_t strlen(const char *s);
size_t strnlen(const char *s, size_t n);
int strcmp(const char* s1, const char* s2);
char* strcpy(char* dest, const char* src);

#endif // _STRING_H
