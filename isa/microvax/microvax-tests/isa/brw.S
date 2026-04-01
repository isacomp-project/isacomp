# Test BRW - Branch Word (longer displacement)
# Unconditional branch with 24-bit displacement

.text
    brw pass
    brb fail

pass:
    brb pass
fail:
    brb fail
