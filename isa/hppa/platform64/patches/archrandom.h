/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _ASM_PARISC_ARCHRANDOM_H
#define _ASM_PARISC_ARCHRANDOM_H

#include <asm/special_insns.h>

static inline size_t __must_check arch_get_random_longs(unsigned long *v, size_t max_longs)
{
	return 0;
}

static inline size_t __must_check arch_get_random_seed_longs(unsigned long *v, size_t max_longs)
{
	size_t i;

	for (i = 0; i < max_longs; i++)
		v[i] = mfctl(16);
	return max_longs;
}

#endif /* _ASM_PARISC_ARCHRANDOM_H */
