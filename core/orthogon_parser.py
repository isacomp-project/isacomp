"""
Orthogon parser for ISA specifications.

Parses orthogon definition files (.isa files containing an `orthogon` block)
into OrthogonDefinition data structures. These are later expanded into mux
trees by orthogon_merger.py when an instruction file uses the orthogon via
a `use` statement.

Grammar (see docs/ISA_GRAMMAR.md for the full specification):

    orthogon_file   = "orthogon" IDENT "{" orthogon_body "}" ;
    orthogon_body   = selector_decl
                      [ uses_block ]
                      provides_block
                      [ writes_block ]
                      { variant_decl }
                      ;
    selector_decl   = "selector" IDENT bit_range ";" ;
    uses_block      = "uses" "{" { state_decl } "}" ;
    provides_block  = "provides" "{" { IDENT bit_range ";" } "}" ;
    writes_block    = "writes" "{" { state_decl } "}" ;
    variant_decl    = "variant" IDENT ":" expression "{" { statement } "}" ;
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .isa_parser import ISAParser, ISALexer, ISAToken


# Additional token patterns for orthogon keywords.
# These are prepended to the lexer's pattern list so they match before IDENTIFIER.
ORTHOGON_TOKEN_PATTERNS = [
    ('ORTHOGON', r'orthogon(?![a-zA-Z0-9_])'),
    ('SELECTOR', r'selector(?![a-zA-Z0-9_])'),
    ('PROVIDES', r'provides(?![a-zA-Z0-9_])'),
    ('WRITES', r'writes(?![a-zA-Z0-9_])'),
    ('USES', r'uses(?![a-zA-Z0-9_])'),
    ('VARIANT', r'variant(?![a-zA-Z0-9_])'),
    ('USE', r'use(?![a-zA-Z0-9_])'),
]


@dataclass
class ProvidesDef:
    """A single provides output declaration."""
    name: str
    bit_high: int
    bit_low: int

    @property
    def bit_width(self) -> int:
        return self.bit_high - self.bit_low + 1


@dataclass
class StateRef:
    """A reference to an isa_state used or written by the orthogon."""
    name: str
    bit_high: int
    bit_low: int
    # For array states: additional dimensions
    array_dims: List[Tuple[int, int]] = field(default_factory=list)
    is_memory: bool = False

    @property
    def bit_width(self) -> int:
        return self.bit_high - self.bit_low + 1


@dataclass
class VariantDef:
    """A single variant within an orthogon."""
    name: str
    # The selector match condition as a parsed AST expression dict
    condition: dict
    # Raw token list for the variant body (parsed lazily during expansion)
    body_tokens: List[ISAToken] = field(default_factory=list)


@dataclass
class OrthogonDefinition:
    """Complete parsed orthogon definition."""
    name: str
    # Selector signal
    selector_name: str
    selector_high: int
    selector_low: int
    # Interface declarations
    uses: List[StateRef] = field(default_factory=list)
    provides: List[ProvidesDef] = field(default_factory=list)
    writes: List[StateRef] = field(default_factory=list)
    # Variants in declaration order
    variants: List[VariantDef] = field(default_factory=list)
    # Source file path (for resolving relative references)
    source_file: Optional[str] = None

    @property
    def selector_width(self) -> int:
        return self.selector_high - self.selector_low + 1

    def provides_by_name(self) -> Dict[str, ProvidesDef]:
        return {p.name: p for p in self.provides}

    def writes_by_name(self) -> Dict[str, StateRef]:
        return {w.name: w for w in self.writes}


class OrthogonLexer(ISALexer):
    """Extended lexer that recognizes orthogon keywords."""

    def __init__(self):
        super().__init__()
        # Insert orthogon keywords before IDENTIFIER so they match first.
        # Find the IDENTIFIER position and insert before it.
        import re
        ident_idx = next(
            i for i, (name, _) in enumerate(self.token_patterns)
            if name == 'IDENTIFIER'
        )
        for j, (name, pattern) in enumerate(ORTHOGON_TOKEN_PATTERNS):
            self.token_patterns.insert(ident_idx + j, (name, pattern))
        # Recompile
        self.compiled_patterns = [
            (name, re.compile(pattern))
            for name, pattern in self.token_patterns
        ]


class OrthogonParser:
    """
    Parser for orthogon definition files.

    Parses the orthogon { ... } block into an OrthogonDefinition data structure.
    Variant bodies are stored as raw token lists — they are parsed into graph
    nodes later by the orthogon_merger when the orthogon is instantiated.
    """

    def __init__(self):
        self.lexer = OrthogonLexer()
        self.tokens: List[ISAToken] = []
        self.current: int = 0

    # ── Token navigation (mirrors ISAParser) ──────────────────────────

    def peek(self) -> ISAToken:
        if self.current >= len(self.tokens):
            return ISAToken('EOF', '', -1, -1)
        return self.tokens[self.current]

    def advance(self) -> ISAToken:
        token = self.peek()
        self.current += 1
        return token

    def check(self, token_type: str) -> bool:
        return not self.is_at_end() and self.peek().type == token_type

    def consume(self, token_type: str, message: str = "") -> ISAToken:
        if self.check(token_type):
            return self.advance()
        token = self.peek()
        raise SyntaxError(
            f"{message or f'Expected {token_type}'} at line {token.line}:{token.column}, "
            f"got {token.type} '{token.value}'"
        )

    def is_at_end(self) -> bool:
        return self.current >= len(self.tokens)

    # ── Entry points ──────────────────────────────────────────────────

    def parse_file(self, filename: str, preprocess: bool = True) -> OrthogonDefinition:
        """Parse an orthogon definition from a file."""
        if preprocess:
            from .isa_parser import ISAParser
            temp_parser = ISAParser()
            text = temp_parser.preprocess(filename)
        else:
            with open(filename, 'r') as f:
                text = f.read()

        defn = self.parse(text)
        defn.source_file = os.path.abspath(filename)
        return defn

    def parse(self, text: str) -> OrthogonDefinition:
        """Parse orthogon definition from text."""
        self.tokens = self.lexer.tokenize(text)
        self.current = 0
        return self._parse_orthogon()

    # ── Top-level orthogon parsing ────────────────────────────────────

    def _parse_orthogon(self) -> OrthogonDefinition:
        """Parse: orthogon NAME { body }"""
        self.consume('ORTHOGON', "Expected 'orthogon'")
        name = self.consume('IDENTIFIER', "Expected orthogon name").value
        self.consume('LBRACE', "Expected '{'")

        defn = OrthogonDefinition(
            name=name,
            selector_name='',
            selector_high=0,
            selector_low=0,
        )

        # Parse selector (required, must come first)
        self._parse_selector(defn)

        # Parse optional uses block
        if self.check('USES'):
            defn.uses = self._parse_uses_block()

        # Parse provides block (required)
        if self.check('PROVIDES'):
            defn.provides = self._parse_provides_block()
        else:
            raise SyntaxError(
                f"Expected 'provides' block in orthogon '{name}' "
                f"at line {self.peek().line}"
            )

        # Parse optional writes block
        if self.check('WRITES'):
            defn.writes = self._parse_writes_block()

        # Parse variants
        while self.check('VARIANT'):
            defn.variants.append(self._parse_variant(defn))

        self.consume('RBRACE', "Expected '}' to close orthogon")

        # Validation
        self._validate(defn)

        return defn

    def _parse_selector(self, defn: OrthogonDefinition):
        """Parse: selector NAME[high:low];"""
        self.consume('SELECTOR', "Expected 'selector'")
        defn.selector_name = self.consume('IDENTIFIER', "Expected selector name").value
        high, low = self._parse_bit_range()
        defn.selector_high = high
        defn.selector_low = low
        self.consume('SEMICOLON', "Expected ';'")

    def _parse_uses_block(self) -> List[StateRef]:
        """Parse: uses { isa_state declarations... }"""
        self.consume('USES', "Expected 'uses'")
        self.consume('LBRACE', "Expected '{'")
        refs = []
        while not self.check('RBRACE') and not self.is_at_end():
            refs.append(self._parse_state_ref())
        self.consume('RBRACE', "Expected '}'")
        return refs

    def _parse_provides_block(self) -> List[ProvidesDef]:
        """Parse: provides { name[h:l]; ... }"""
        self.consume('PROVIDES', "Expected 'provides'")
        self.consume('LBRACE', "Expected '{'")
        provides = []
        while not self.check('RBRACE') and not self.is_at_end():
            name = self.consume('IDENTIFIER', "Expected provides name").value
            high, low = self._parse_bit_range()
            self.consume('SEMICOLON', "Expected ';'")
            provides.append(ProvidesDef(name=name, bit_high=high, bit_low=low))
        self.consume('RBRACE', "Expected '}'")
        return provides

    def _parse_writes_block(self) -> List[StateRef]:
        """Parse: writes { isa_state declarations... }"""
        self.consume('WRITES', "Expected 'writes'")
        self.consume('LBRACE', "Expected '{'")
        refs = []
        while not self.check('RBRACE') and not self.is_at_end():
            refs.append(self._parse_state_ref())
        self.consume('RBRACE', "Expected '}'")
        return refs

    def _parse_state_ref(self) -> StateRef:
        """Parse: isa_state NAME[h:l] {[h:l]}* ;"""
        self.consume('ISA_STATE', "Expected 'isa_state'")
        name = self.consume('IDENTIFIER', "Expected state name").value
        high, low = self._parse_bit_range()
        array_dims = []
        is_memory = False
        # Parse optional array dimensions
        while self.check('LBRACKET'):
            dim_high, dim_low = self._parse_bit_range()
            array_dims.append((dim_high, dim_low))
            is_memory = True
        self.consume('SEMICOLON', "Expected ';'")
        return StateRef(
            name=name, bit_high=high, bit_low=low,
            array_dims=array_dims, is_memory=is_memory,
        )

    def _parse_variant(self, defn: OrthogonDefinition) -> VariantDef:
        """Parse: variant NAME : condition { body }"""
        self.consume('VARIANT', "Expected 'variant'")
        name = self.consume('IDENTIFIER', "Expected variant name").value
        self.consume('COLON', "Expected ':'")

        # Parse the selector match condition expression.
        # We use a temporary ISAParser to leverage its expression parsing.
        condition = self._parse_expression_until_lbrace()

        self.consume('LBRACE', "Expected '{'")

        # Collect body tokens (brace-balanced) without parsing them.
        # They will be parsed into graph nodes during orthogon expansion.
        body_tokens = self._collect_balanced_tokens()

        self.consume('RBRACE', "Expected '}'")

        return VariantDef(name=name, condition=condition, body_tokens=body_tokens)

    # ── Expression parsing (reuses ISAParser) ─────────────────────────

    def _parse_expression_until_lbrace(self) -> dict:
        """
        Parse an expression that ends when we see '{'.

        We delegate to ISAParser's expression parser by extracting the
        relevant token subsequence.
        """
        # Collect tokens until we see LBRACE at nesting depth 0
        expr_tokens = []
        while not self.check('LBRACE') and not self.is_at_end():
            expr_tokens.append(self.advance())

        if not expr_tokens:
            raise SyntaxError("Empty variant condition expression")

        # Use ISAParser to parse the expression
        parser = ISAParser()
        parser.tokens = expr_tokens
        parser.current = 0
        parser.loop_vars = {}
        parser.intermediate_values = {}
        parser.current_graph = None
        return parser.parse_expression()

    def _collect_balanced_tokens(self) -> List[ISAToken]:
        """Collect tokens inside a brace-balanced block (not including outer braces)."""
        tokens = []
        depth = 0
        while not self.is_at_end():
            if self.check('LBRACE'):
                depth += 1
                tokens.append(self.advance())
            elif self.check('RBRACE'):
                if depth == 0:
                    break  # Matching close brace — don't consume it
                depth -= 1
                tokens.append(self.advance())
            else:
                tokens.append(self.advance())
        return tokens

    # ── Helpers ────────────────────────────────────────────────────────

    def _parse_bit_range(self) -> Tuple[int, int]:
        """Parse [high:low] and return (high, low)."""
        self.consume('LBRACKET', "Expected '['")
        high_tok = self.consume('NUMBER', "Expected high bit")
        high = int(high_tok.value)
        self.consume('COLON', "Expected ':'")
        low_tok = self.consume('NUMBER', "Expected low bit")
        low = int(low_tok.value)
        self.consume('RBRACKET', "Expected ']'")
        return (high, low)

    # ── Validation ────────────────────────────────────────────────────

    def _validate(self, defn: OrthogonDefinition):
        """Validate the orthogon definition for consistency."""
        if not defn.variants:
            raise ValueError(f"Orthogon '{defn.name}' has no variants")

        if not defn.provides:
            raise ValueError(f"Orthogon '{defn.name}' has no provides declarations")

        # Check variant names are unique
        names = [v.name for v in defn.variants]
        dupes = [n for n in names if names.count(n) > 1]
        if dupes:
            raise ValueError(
                f"Orthogon '{defn.name}' has duplicate variant names: {set(dupes)}"
            )

        # Check that uses and writes names don't overlap
        uses_names = {u.name for u in defn.uses}
        writes_names = {w.name for w in defn.writes}
        overlap = uses_names & writes_names
        if overlap:
            raise ValueError(
                f"Orthogon '{defn.name}': states {overlap} appear in both 'uses' and 'writes'. "
                f"A state should be in 'uses' (read-only) or 'writes' (read-write), not both."
            )


def parse_orthogon_file(filename: str, preprocess: bool = True) -> OrthogonDefinition:
    """Convenience function to parse an orthogon file."""
    parser = OrthogonParser()
    return parser.parse_file(filename, preprocess=preprocess)


def is_orthogon_file(filename: str) -> bool:
    """
    Check if a file contains an orthogon definition (quick heuristic).

    Reads the first few non-comment, non-empty lines looking for the
    'orthogon' keyword.
    """
    try:
        with open(filename, 'r') as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith('//') or stripped.startswith('#'):
                    continue
                return stripped.startswith('orthogon ')
    except (IOError, OSError):
        return False
    return False
