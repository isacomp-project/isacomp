# Simple arithmetic test
# mem[10] = mem[10] - mem[9]
# mem[9] contains 5, mem[10] contains 10
# After execution, mem[10] should contain 5

# Subtract mem[9] from mem[10]
9 10 6    # If result <= 0, jump to 6, else continue to 3

# Halt
.halt

# Data section
.word 5   # Address 9: value 5
.word 10  # Address 10: value 10
