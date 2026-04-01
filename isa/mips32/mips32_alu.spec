// Complete ALU specification for MIPS32 instruction set
// Covers all unique arithmetic and logical operations used by MIPS32 instructions
alu_module MIPS32_ALU[31:0];

// Arithmetic operations
operation add {
    opcode = 4'b0000;
    function = "result = operand_a + operand_b;";
    description = "32-bit addition";
}

operation sub {
    opcode = 4'b0001;
    function = "result = operand_a - operand_b;";
    description = "32-bit subtraction";
}

// Logical operations
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

operation nor {
    opcode = 4'b0100;
    function = "result = ~(operand_a | operand_b);";
    description = "Bitwise NOR";
}

// Shift operations
operation sll {
    opcode = 4'b0101;
    function = "result = operand_a << operand_b;";
    description = "Shift left logical";
}

operation srl {
    opcode = 4'b0110;
    function = "result = operand_a >> operand_b;";
    description = "Shift right logical";
}

// Comparison operations
operation eq {
    opcode = 4'b0111;
    function = "result = (operand_a == operand_b) ? 32'h1 : 32'h0;";
    description = "Equality comparison";
}

operation neq {
    opcode = 4'b1000;
    function = "result = (operand_a != operand_b) ? 32'h1 : 32'h0;";
    description = "Not equal comparison";
}

operation slt {
    opcode = 4'b1001;
    function = "result = ($signed(operand_a) < $signed(operand_b)) ? 32'h1 : 32'h0;";
    description = "Set less than (signed)";
}

operation sltu {
    opcode = 4'b1010;
    function = "result = (operand_a < operand_b) ? 32'h1 : 32'h0;";
    description = "Set less than unsigned";
}
