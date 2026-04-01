# Simple countdown loop test
# Countdown from 5 to 0
# SUBLEQ branches when result <= 0

loop:
    # Decrement counter: counter = counter - one
    one counter next    # If counter <= 0 after sub, jump to next (exit loop)

    # Unconditional jump back to loop (subtract 0 from 0, result is 0, always branches)
    zero zero loop

# Exit loop
next:
    .halt

# Data
zero:    .word 0
one:     .word 1
counter: .word 5
