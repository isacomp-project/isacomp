"""
ALU specification parser.

Parses ALU module specifications using ISA-style syntax, reusing the ISALexer
tokenizer for consistent literal and identifier handling.

Syntax::

    alu_module ProcessorALU[31:0];

    operation add {
        opcode = 3'b000;
        function = "result = operand_a + operand_b;";
        description = "32-bit addition";
    }
"""

import logging
import re
from typing import Dict, List, Optional

from core.isa_parser import ISALexer, ISAToken
from opt.alu_integration import ALUSpec

logger = logging.getLogger(__name__)

# Canonical mapping from operation names to the operator symbols used in
# ResourceGraph expression nodes.  Signed comparison operators use the
# ``<s`` / ``>=s`` suffixes produced by the ISA parser.
OPERATOR_MAPPING = {
    'add': '+', 'sub': '-',
    'or': '|', 'and': '&', 'xor': '^', 'nor': '~|',
    'shl': '<<', 'shr': '>>', 'sll': '<<', 'srl': '>>',
    'sra': '>>>',
    'mul': '*', 'div': '/',
    'slt': '<s', 'sltu': '<',
    'sge': '>=s', 'sgeu': '>=',
    'eq': '==', 'neq': '!=',
}


class ALUOperation:
    """A complete ALU operation definition with optional Verilog function body."""

    def __init__(self, name: str, opcode: int, function: str = "", description: str = ""):
        self.name = name
        self.opcode = opcode
        self.function = function
        self.description = description

    def __repr__(self):
        return f"ALUOperation({self.name!r}, opcode={self.opcode}, func={self.function!r})"


class EnhancedALUSpec(ALUSpec):
    """ALU specification that can carry per-operation Verilog function bodies."""

    def __init__(self, name: str, input_width: int = 32, output_width: int = 32):
        super().__init__(name, input_width, output_width)
        self.operation_definitions: Dict[str, ALUOperation] = {}

    def add_operation_with_function(
        self, name: str, opcode: int, function: str = "", description: str = ""
    ):
        """Add an operation together with its Verilog function body."""
        operator = OPERATOR_MAPPING.get(name, name)
        self.add_operation(operator, opcode, description)

        op_def = ALUOperation(name, opcode, function, description)
        self.operation_definitions[name] = op_def
        return op_def


class ALULexer(ISALexer):
    """ISALexer extended with ALU-specific keywords and string literals."""

    def __init__(self):
        super().__init__()
        alu_keywords = [
            ('ALU_MODULE', r'alu_module(?![a-zA-Z0-9_])'),
            ('OPERATION', r'operation(?![a-zA-Z0-9_])'),
            ('FUNCTION', r'function(?![a-zA-Z0-9_])'),
            ('DESCRIPTION', r'description(?![a-zA-Z0-9_])'),
            ('OPCODE', r'opcode(?![a-zA-Z0-9_])'),
            ('STRING', r'"[^"]*"'),
        ]
        # Insert ALU keywords before the IDENTIFIER pattern so they take priority.
        idx = next(
            i for i, (name, _) in enumerate(self.token_patterns) if name == 'IDENTIFIER'
        )
        for j, pattern in enumerate(alu_keywords):
            self.token_patterns.insert(idx + j, pattern)
        # Recompile after mutation.
        self.compiled_patterns = [
            (name, re.compile(pattern)) for name, pattern in self.token_patterns
        ]


class ALUSpecParser:
    """Token-based ALU spec parser.

    Uses ``ALULexer`` (an extension of ``ISALexer``) so that Verilog-style
    sized literals (``3'b000``, ``4'hF``, ``6'd32``) are tokenised identically
    to the main ISA parser.
    """

    def __init__(self):
        self.lexer = ALULexer()
        self.tokens: List[ISAToken] = []
        self.current: int = 0

    # -- public API ----------------------------------------------------------

    def parse_file(self, filename: str) -> List[EnhancedALUSpec]:
        """Parse an ALU spec file and return a list of ALU specs."""
        with open(filename, 'r') as f:
            content = f.read()
        return self.parse(content)

    def parse(self, content: str) -> List[EnhancedALUSpec]:
        """Parse ALU spec text and return a list of ALU specs."""
        self.tokens = self.lexer.tokenize(content)
        self.current = 0
        specs: List[EnhancedALUSpec] = []
        current_alu: Optional[EnhancedALUSpec] = None

        while not self.is_at_end():
            if self.check('ALU_MODULE'):
                current_alu = self._parse_alu_declaration()
                specs.append(current_alu)
            elif self.check('OPERATION'):
                if current_alu is None:
                    tok = self.peek()
                    raise ValueError(
                        f"Operation defined outside alu_module at line {tok.line}"
                    )
                self._parse_operation(current_alu)
            else:
                tok = self.peek()
                raise ValueError(
                    f"Unexpected token {tok.type!r} ({tok.value!r}) at line {tok.line}"
                )

        return specs

    # -- declaration parsing -------------------------------------------------

    def _parse_alu_declaration(self) -> EnhancedALUSpec:
        """Parse ``alu_module Name[high:low];``."""
        self.consume('ALU_MODULE', "Expected 'alu_module'")
        name = self.consume('IDENTIFIER', "Expected ALU module name").value
        width = self._parse_bit_range() if self.check('LBRACKET') else 32
        if self.check('SEMICOLON'):
            self.advance()
        logger.debug("Parsed ALU declaration: %s (%d bits)", name, width)
        return EnhancedALUSpec(name, input_width=width, output_width=width)

    def _parse_bit_range(self) -> int:
        """Parse ``[high:low]`` and return the width (high - low + 1)."""
        self.consume('LBRACKET', "Expected '['")
        high = self._parse_number()
        self.consume('COLON', "Expected ':'")
        low = self._parse_number()
        self.consume('RBRACKET', "Expected ']'")
        return high - low + 1

    # -- operation parsing ---------------------------------------------------

    def _parse_operation(self, alu: EnhancedALUSpec):
        """Parse ``operation name { opcode = ...; function = "..."; ... }``."""
        self.consume('OPERATION', "Expected 'operation'")
        name = self.consume('IDENTIFIER', "Expected operation name").value

        if not self.check('LBRACE'):
            tok = self.peek()
            raise ValueError(
                f"Expected '{{' after operation name at line {tok.line}"
            )
        self._parse_block_operation(alu, name)

    def _parse_block_operation(self, alu: EnhancedALUSpec, name: str):
        """Parse ``operation name { opcode = ...; function = "..."; ... }``."""
        self.consume('LBRACE', "Expected '{'")
        opcode = 0
        function = ""
        description = ""

        while not self.check('RBRACE') and not self.is_at_end():
            if self.check('OPCODE'):
                self.advance()
                self.consume('EQUALS', "Expected '='")
                opcode = self._parse_opcode_value()
                if self.check('SEMICOLON'):
                    self.advance()
            elif self.check('FUNCTION'):
                self.advance()
                self.consume('EQUALS', "Expected '='")
                function = self._parse_string_value()
                if self.check('SEMICOLON'):
                    self.advance()
            elif self.check('DESCRIPTION'):
                self.advance()
                self.consume('EQUALS', "Expected '='")
                description = self._parse_string_value()
                if self.check('SEMICOLON'):
                    self.advance()
            else:
                # Skip unrecognised field.
                self.advance()

        self.consume('RBRACE', "Expected '}'")
        alu.add_operation_with_function(name, opcode, function, description)
        logger.debug("  operation %s = %d (block)", name, opcode)

    # -- value parsing -------------------------------------------------------

    def _parse_opcode_value(self) -> int:
        """Parse a Verilog-style opcode literal and return its integer value.

        Handles the same token types as ``ISAParser.parse_primary()``:
        BINARY_LITERAL (``3'b000``), VERILOG_HEX_LITERAL (``4'hF``),
        DECIMAL_LITERAL (``6'd32``), HEX_NUMBER (``0x1``), and plain NUMBER.
        """
        if self.match('BINARY_LITERAL'):
            tok = self.previous()
            _width, bits = tok.value.split("'b", 1)
            return int(bits, 2)
        if self.match('VERILOG_HEX_LITERAL'):
            tok = self.previous()
            _width, hex_digits = tok.value.split("'h", 1)
            return int(hex_digits, 16)
        if self.match('DECIMAL_LITERAL'):
            tok = self.previous()
            _width, dec_digits = tok.value.split("'d", 1)
            return int(dec_digits, 10)
        if self.match('HEX_NUMBER'):
            return int(self.previous().value, 16)
        if self.match('NUMBER'):
            return int(self.previous().value)

        tok = self.peek()
        raise ValueError(f"Expected opcode value at line {tok.line}, got {tok.type}")

    def _parse_number(self) -> int:
        """Parse a plain integer (NUMBER or HEX_NUMBER)."""
        if self.match('NUMBER'):
            return int(self.previous().value)
        if self.match('HEX_NUMBER'):
            return int(self.previous().value, 16)
        tok = self.peek()
        raise ValueError(f"Expected number at line {tok.line}, got {tok.type}")

    def _parse_string_value(self) -> str:
        """Parse a quoted string and return its contents (without quotes)."""
        tok = self.consume('STRING', "Expected quoted string")
        return tok.value[1:-1]  # strip surrounding quotes

    # -- token navigation (same interface as ISAParser) ----------------------

    def match(self, *types: str) -> bool:
        for token_type in types:
            if self.check(token_type):
                self.advance()
                return True
        return False

    def check(self, token_type: str) -> bool:
        if self.is_at_end():
            return False
        return self.peek().type == token_type

    def advance(self) -> ISAToken:
        if not self.is_at_end():
            self.current += 1
        return self.previous()

    def is_at_end(self) -> bool:
        return self.current >= len(self.tokens)

    def peek(self) -> ISAToken:
        if self.current >= len(self.tokens):
            return ISAToken('EOF', '', 0, 0)
        return self.tokens[self.current]

    def previous(self) -> ISAToken:
        return self.tokens[self.current - 1]

    def consume(self, token_type: str, message: str) -> ISAToken:
        if self.check(token_type):
            return self.advance()
        tok = self.peek()
        raise ValueError(
            f"{message}. Got {tok.type} '{tok.value}' at line {tok.line}"
        )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def parse_alu_spec_file(filename: str) -> List[EnhancedALUSpec]:
    """Parse ALU specifications from a file."""
    return ALUSpecParser().parse_file(filename)


def parse_alu_spec(content: str) -> List[EnhancedALUSpec]:
    """Parse ALU specifications from a string."""
    return ALUSpecParser().parse(content)
