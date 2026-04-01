// ALU specification covering all RV32I arithmetic, logic, shift, and
// comparison operations.  Opcodes are 4 bits to accommodate 16 operations.
alu_module ProcessorALU[31:0];

// Arithmetic
operation add {
    opcode = 4'b0000;
    function = "result = operand_a + operand_b;";
    description = "Addition";
}

operation sub {
    opcode = 4'b0001;
    function = "result = operand_a - operand_b;";
    description = "Subtraction";
}

// Bitwise logic
operation and {
    opcode = 4'b0010;
    function = "result = operand_a & operand_b;";
    description = "Bitwise AND";
}

operation or {
    opcode = 4'b0011;
    function = "result = operand_a | operand_b;";
    description = "Bitwise OR";
}

operation xor {
    opcode = 4'b0100;
    function = "result = operand_a ^ operand_b;";
    description = "Bitwise XOR";
}

// Shifts
operation sll {
    opcode = 4'b0101;
    function = "result = operand_a << operand_b[4:0];";
    description = "Shift left logical";
}

operation srl {
    opcode = 4'b0110;
    function = "result = operand_a >> operand_b[4:0];";
    description = "Shift right logical";
}

operation sra {
    opcode = 4'b0111;
    function = "result = $signed(operand_a) >>> operand_b[4:0];";
    description = "Shift right arithmetic";
}

// Comparisons (signed)
operation slt {
    opcode = 4'b1000;
    function = "result = ($signed(operand_a) < $signed(operand_b)) ? 32'h1 : 32'h0;";
    description = "Set less than (signed)";
}

// Comparisons (unsigned)
operation sltu {
    opcode = 4'b1001;
    function = "result = (operand_a < operand_b) ? 32'h1 : 32'h0;";
    description = "Set less than (unsigned)";
}

// Equality / inequality (for branches)
operation eq {
    opcode = 4'b1010;
    function = "result = (operand_a == operand_b) ? 32'h1 : 32'h0;";
    description = "Equality comparison";
}

operation neq {
    opcode = 4'b1011;
    function = "result = (operand_a != operand_b) ? 32'h1 : 32'h0;";
    description = "Not-equal comparison";
}

// Signed greater-or-equal (for bge)
operation sge {
    opcode = 4'b1100;
    function = "result = ($signed(operand_a) >= $signed(operand_b)) ? 32'h1 : 32'h0;";
    description = "Signed greater-or-equal";
}

// Unsigned greater-or-equal (for bgeu)
operation sgeu {
    opcode = 4'b1101;
    function = "result = (operand_a >= operand_b) ? 32'h1 : 32'h0;";
    description = "Unsigned greater-or-equal";
}
