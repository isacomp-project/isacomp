# ISAComp Benchmark C Runtime Startup - RV64I
# Pure RV64I - no CSR instructions

#define LREG ld
#define SREG sd
#define REGBYTES 8

  .section ".text.init"
  .globl _start
_start:
  # Initialize all registers to zero
  li  x1, 0
  li  x2, 0
  li  x3, 0
  li  x4, 0
  li  x5, 0
  li  x6, 0
  li  x7, 0
  li  x8, 0
  li  x9, 0
  li  x10,0
  li  x11,0
  li  x12,0
  li  x13,0
  li  x14,0
  li  x15,0
  li  x16,0
  li  x17,0
  li  x18,0
  li  x19,0
  li  x20,0
  li  x21,0
  li  x22,0
  li  x23,0
  li  x24,0
  li  x25,0
  li  x26,0
  li  x27,0
  li  x28,0
  li  x29,0
  li  x30,0
  li  x31,0

  # Initialize global pointer
.option push
.option norelax
  la gp, __global_pointer$
.option pop

  # Initialize stack pointer (at 64KB for RV64I)
  li sp, 0x10000

  # Initialize thread pointer (after stack)
  la tp, _end
  addi tp, tp, 63
  andi tp, tp, -64

  # No trap handler - no exception support

  # Initialize TLS
  jal init_tls

  # Call main with argc=0, argv=0
  li a0, 0
  li a1, 0
  jal main

  # Handle return value: 0 = pass, non-zero = fail
  beqz a0, pass
  j fail

  .align 3
  .globl pass
pass:
  fence
  li gp, 1            # gp=1 indicates pass
1:
  j 1b                # Infinite loop at known address

  .align 3
  .globl fail
fail:
  fence
  # gp already contains the failing test case number
  # or the return value from main if it's a benchmark
  beqz a0, 1f
  mv gp, a0           # Use return value as gp if non-zero
1:
  slli gp, gp, 1      # Shift left by 1
  ori gp, gp, 1       # Set LSB to 1
2:
  j 2b                # Infinite loop at known address

# Initialize thread-local storage
init_tls:
  # Simplified - just return for now
  ret

.section ".tohost","aw",@progbits
.align 6
.globl tohost
tohost: .dword 0
.align 6
.globl fromhost
fromhost: .dword 0
