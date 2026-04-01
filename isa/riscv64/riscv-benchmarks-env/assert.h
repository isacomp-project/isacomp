// Minimal assert.h for ISAComp RV64I benchmarks

#ifndef _ASSERT_H
#define _ASSERT_H

extern void abort(void);

#define assert(x) do { if (!(x)) abort(); } while (0)

#endif // _ASSERT_H
