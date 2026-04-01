use regex::Regex;
use std::fmt;

/// All token types produced by the ISA lexer.
#[derive(Debug, Clone, PartialEq)]
pub enum TokenType {
    // Keywords
    IsaState,
    Mem,
    Var,
    Assume,
    For,
    If,
    Else,
    Case,
    When,
    Aspect,
    Gates,
    Ext,
    Push,
    Sensitive,
    Flush,
    Cam,
    Ctz,
    Clz,
    Of,
    FpType,
    FpcmpRes,

    // Identifiers and literals
    Identifier,
    VerilogHexLiteral,
    BinaryWildcard,
    BinaryLiteral,
    DecimalLiteral,
    HexNumber,
    Number,

    // Multi-character operators
    ArithRightShift,
    LeftShift,
    RightShift,
    NotEquals,
    DoubleEquals,
    LessEqualSigned,
    GreaterEqualSigned,
    LessThanSigned,
    GreaterThanSigned,
    LessEqual,
    GreaterEqual,
    LessThan,
    GreaterThan,
    LogicalAnd,
    LogicalOr,
    DivideSigned,
    ModuloSigned,

    // Single-character tokens
    Lbrace,
    Rbrace,
    Lbracket,
    Rbracket,
    Lparen,
    Rparen,
    Semicolon,
    Colon,
    Dot,
    Equals,
    Plus,
    Minus,
    Multiply,
    Divide,
    Modulo,
    Ampersand,
    Pipe,
    Caret,
    Tilde,
    LogicalNot,
    Question,
    At,
    Comma,

    // End of file
    Eof,
}

impl fmt::Display for TokenType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let s = match self {
            TokenType::IsaState => "ISA_STATE",
            TokenType::Mem => "MEM",
            TokenType::Var => "VAR",
            TokenType::Assume => "ASSUME",
            TokenType::For => "FOR",
            TokenType::If => "IF",
            TokenType::Else => "ELSE",
            TokenType::Case => "CASE",
            TokenType::When => "WHEN",
            TokenType::Aspect => "ASPECT",
            TokenType::Gates => "GATES",
            TokenType::Ext => "EXT",
            TokenType::Push => "PUSH",
            TokenType::Sensitive => "SENSITIVE",
            TokenType::Flush => "FLUSH",
            TokenType::Cam => "CAM",
            TokenType::Ctz => "CTZ",
            TokenType::Clz => "CLZ",
            TokenType::Of => "OF",
            TokenType::FpType => "FP_TYPE",
            TokenType::FpcmpRes => "FPCMP_RES",
            TokenType::Identifier => "IDENTIFIER",
            TokenType::VerilogHexLiteral => "VERILOG_HEX_LITERAL",
            TokenType::BinaryWildcard => "BINARY_WILDCARD",
            TokenType::BinaryLiteral => "BINARY_LITERAL",
            TokenType::DecimalLiteral => "DECIMAL_LITERAL",
            TokenType::HexNumber => "HEX_NUMBER",
            TokenType::Number => "NUMBER",
            TokenType::ArithRightShift => "ARITH_RIGHT_SHIFT",
            TokenType::LeftShift => "LEFT_SHIFT",
            TokenType::RightShift => "RIGHT_SHIFT",
            TokenType::NotEquals => "NOT_EQUALS",
            TokenType::DoubleEquals => "DOUBLE_EQUALS",
            TokenType::LessEqualSigned => "LESS_EQUAL_SIGNED",
            TokenType::GreaterEqualSigned => "GREATER_EQUAL_SIGNED",
            TokenType::LessThanSigned => "LESS_THAN_SIGNED",
            TokenType::GreaterThanSigned => "GREATER_THAN_SIGNED",
            TokenType::LessEqual => "LESS_EQUAL",
            TokenType::GreaterEqual => "GREATER_EQUAL",
            TokenType::LessThan => "LESS_THAN",
            TokenType::GreaterThan => "GREATER_THAN",
            TokenType::LogicalAnd => "LOGICAL_AND",
            TokenType::LogicalOr => "LOGICAL_OR",
            TokenType::DivideSigned => "DIVIDE_SIGNED",
            TokenType::ModuloSigned => "MODULO_SIGNED",
            TokenType::Lbrace => "LBRACE",
            TokenType::Rbrace => "RBRACE",
            TokenType::Lbracket => "LBRACKET",
            TokenType::Rbracket => "RBRACKET",
            TokenType::Lparen => "LPAREN",
            TokenType::Rparen => "RPAREN",
            TokenType::Semicolon => "SEMICOLON",
            TokenType::Colon => "COLON",
            TokenType::Dot => "DOT",
            TokenType::Equals => "EQUALS",
            TokenType::Plus => "PLUS",
            TokenType::Minus => "MINUS",
            TokenType::Multiply => "MULTIPLY",
            TokenType::Divide => "DIVIDE",
            TokenType::Modulo => "MODULO",
            TokenType::Ampersand => "AMPERSAND",
            TokenType::Pipe => "PIPE",
            TokenType::Caret => "CARET",
            TokenType::Tilde => "TILDE",
            TokenType::LogicalNot => "LOGICAL_NOT",
            TokenType::Question => "QUESTION",
            TokenType::At => "AT",
            TokenType::Comma => "COMMA",
            TokenType::Eof => "EOF",
        };
        write!(f, "{}", s)
    }
}

/// A single token produced by the lexer.
#[derive(Debug, Clone)]
pub struct ISAToken {
    pub type_: TokenType,
    pub value: String,
    pub line: usize,
    pub column: usize,
}

impl fmt::Display for ISAToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Token({}, '{}', {}:{})",
            self.type_, self.value, self.line, self.column
        )
    }
}

/// Returns true if `c` is an ASCII alphanumeric character or underscore.
/// Used for keyword word-boundary checks.
fn is_word_char(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'_'
}

/// Check whether `word` is one of the recognised FP type keywords.
///
/// Matches: fp16, fp32, fp64, fp128, fp16_res, fp32_res, fp64_res, fp128_res.
/// The caller has already ensured `word` is a maximal identifier span (bounded
/// by non-word characters), so no explicit word-boundary check is needed here.
fn match_fp_type(word: &str) -> bool {
    matches!(
        word,
        "fp16" | "fp32" | "fp64" | "fp128" | "fp16_res" | "fp32_res" | "fp64_res" | "fp128_res"
    )
}

/// The ISA specification lexer. Tokenizes `.isa` files into a stream of
/// [`ISAToken`] values.
///
/// Keywords are matched with word-boundary semantics (not followed by
/// alphanumeric or underscore). Comments and whitespace are consumed but
/// never emitted.
pub struct ISALexer {
    // Compiled regexes for complex numeric literal patterns.
    // Each regex is anchored (^) to match only at the start of the remaining slice.
    re_verilog_hex: Regex,
    re_binary_wildcard: Regex,
    re_binary_literal: Regex,
    re_decimal_literal: Regex,
    re_hex_number: Regex,
}

impl ISALexer {
    /// Create a new lexer instance with pre-compiled regex patterns.
    pub fn new() -> Self {
        ISALexer {
            re_verilog_hex: Regex::new(r"^\d+'h[0-9a-fA-F]+").unwrap(),
            re_binary_wildcard: Regex::new(r"^0b[01*]+").unwrap(),
            re_binary_literal: Regex::new(r"^\d+'b[01]+").unwrap(),
            re_decimal_literal: Regex::new(r"^\d+'d\d+").unwrap(),
            re_hex_number: Regex::new(r"^0x[0-9a-fA-F]+").unwrap(),
        }
    }

    /// Tokenize the given ISA source text.
    ///
    /// Returns a `Vec<ISAToken>` on success, or an error string describing
    /// the location of the first unrecognized character.
    pub fn tokenize(&self, text: &str) -> Result<Vec<ISAToken>, String> {
        let mut tokens = Vec::new();
        let lines: Vec<&str> = text.split('\n').collect();

        for (line_idx, line) in lines.iter().enumerate() {
            let line_num = line_idx + 1;
            let bytes = line.as_bytes();
            let len = bytes.len();
            let mut pos: usize = 0; // 0-based byte offset into line

            while pos < len {
                let col = pos + 1; // 1-based column for token reporting
                let b = bytes[pos];

                // --- Whitespace (skip) ---
                if b.is_ascii_whitespace() {
                    pos += 1;
                    while pos < len && bytes[pos].is_ascii_whitespace() {
                        pos += 1;
                    }
                    continue;
                }

                // --- Comment (skip rest of line) ---
                if b == b'/' && pos + 1 < len && bytes[pos + 1] == b'/' {
                    // Comment runs to end of line; consume and continue to next line
                    break;
                }

                // --- Try to match a token ---
                if let Some((tt, matched_len)) = self.try_match(bytes, pos, len, line) {
                    let value = &line[pos..pos + matched_len];
                    tokens.push(ISAToken {
                        type_: tt,
                        value: value.to_string(),
                        line: line_num,
                        column: col,
                    });
                    pos += matched_len;
                } else {
                    let ch = line[pos..].chars().next().unwrap_or('?');
                    return Err(format!(
                        "Invalid character at line {}, column {}: '{}'",
                        line_num, col, ch
                    ));
                }
            }
        }

        Ok(tokens)
    }

    /// Try to match a token at the given byte position in the line.
    /// Returns `Some((TokenType, length))` on success or `None`.
    ///
    /// The matching follows the same priority order as the Python
    /// `ISALexer.token_patterns` list.
    fn try_match(
        &self,
        bytes: &[u8],
        pos: usize,
        len: usize,
        line: &str,
    ) -> Option<(TokenType, usize)> {
        let b = bytes[pos];
        let remaining = &line[pos..];

        // ---------------------------------------------------------------
        // Identifiers and keywords (starts with [a-zA-Z_])
        // ---------------------------------------------------------------
        if b.is_ascii_alphabetic() || b == b'_' {
            // Consume the full identifier span
            let mut end = pos + 1;
            while end < len && is_word_char(bytes[end]) {
                end += 1;
            }
            let word = &line[pos..end];
            let word_len = end - pos;

            // Keywords are matched against the full word. Because we
            // already consumed to the word boundary, the "not followed by
            // alphanumeric/_" constraint from the Python regex is
            // implicitly satisfied: if the keyword were a prefix of a
            // longer identifier, `word` would be that longer identifier
            // and would NOT match the keyword string.

            // FP_TYPE keywords: fp16, fp32, fp64, fp128 and their _res variants.
            // Checked before the keyword match table because in the Python
            // lexer FP_TYPE comes before IDENTIFIER but the match table
            // below only handles exact whole-word matches.
            if word == "fpcmp_res" {
                return Some((TokenType::FpcmpRes, word_len));
            }
            if match_fp_type(word) {
                return Some((TokenType::FpType, word_len));
            }

            let tt = match word {
                "isa_state" => Some(TokenType::IsaState),
                "mem" => Some(TokenType::Mem),
                "var" => Some(TokenType::Var),
                "assume" => Some(TokenType::Assume),
                "for" => Some(TokenType::For),
                "if" => Some(TokenType::If),
                "else" => Some(TokenType::Else),
                "case" => Some(TokenType::Case),
                "when" => Some(TokenType::When),
                "aspect" => Some(TokenType::Aspect),
                "gates" => Some(TokenType::Gates),
                "ext" => Some(TokenType::Ext),
                "push" => Some(TokenType::Push),
                "sensitive" => Some(TokenType::Sensitive),
                "flush" => Some(TokenType::Flush),
                "cam" => Some(TokenType::Cam),
                "ctz" => Some(TokenType::Ctz),
                "clz" => Some(TokenType::Clz),
                "of" => Some(TokenType::Of),
                _ => None,
            };

            if let Some(token_type) = tt {
                return Some((token_type, word_len));
            }

            // No keyword matched -- it is a plain IDENTIFIER
            return Some((TokenType::Identifier, word_len));
        }

        // ---------------------------------------------------------------
        // Numeric literals (starts with a digit)
        // ---------------------------------------------------------------
        if b.is_ascii_digit() {
            // Try the complex numeric patterns via regex (applied to the
            // remaining slice). Order matters: Verilog hex/binary/decimal
            // before plain hex and plain number.
            if let Some(m) = self.re_verilog_hex.find(remaining) {
                return Some((TokenType::VerilogHexLiteral, m.len()));
            }
            if let Some(m) = self.re_binary_wildcard.find(remaining) {
                return Some((TokenType::BinaryWildcard, m.len()));
            }
            if let Some(m) = self.re_binary_literal.find(remaining) {
                return Some((TokenType::BinaryLiteral, m.len()));
            }
            if let Some(m) = self.re_decimal_literal.find(remaining) {
                return Some((TokenType::DecimalLiteral, m.len()));
            }
            if let Some(m) = self.re_hex_number.find(remaining) {
                return Some((TokenType::HexNumber, m.len()));
            }

            // Plain NUMBER: consume consecutive digits
            let mut end = pos + 1;
            while end < len && bytes[end].is_ascii_digit() {
                end += 1;
            }
            return Some((TokenType::Number, end - pos));
        }

        // ---------------------------------------------------------------
        // Operators and punctuation (manual matching)
        // ---------------------------------------------------------------
        let next = if pos + 1 < len { bytes[pos + 1] } else { 0 };
        let next2 = if pos + 2 < len { bytes[pos + 2] } else { 0 };

        match b {
            b'>' => {
                if next == b'>' && next2 == b'>' {
                    // >>>
                    Some((TokenType::ArithRightShift, 3))
                } else if next == b'>' {
                    // >>
                    Some((TokenType::RightShift, 2))
                } else if next == b'=' {
                    if next2 == b's' && (pos + 3 >= len || !is_word_char(bytes[pos + 3])) {
                        // >=s (signed)
                        Some((TokenType::GreaterEqualSigned, 3))
                    } else {
                        // >=
                        Some((TokenType::GreaterEqual, 2))
                    }
                } else if next == b's' && (pos + 2 >= len || !is_word_char(bytes[pos + 2])) {
                    // >s (signed)
                    Some((TokenType::GreaterThanSigned, 2))
                } else {
                    // >
                    Some((TokenType::GreaterThan, 1))
                }
            }
            b'<' => {
                if next == b'<' {
                    // <<
                    Some((TokenType::LeftShift, 2))
                } else if next == b'=' {
                    if next2 == b's' && (pos + 3 >= len || !is_word_char(bytes[pos + 3])) {
                        // <=s (signed)
                        Some((TokenType::LessEqualSigned, 3))
                    } else {
                        // <=
                        Some((TokenType::LessEqual, 2))
                    }
                } else if next == b's' && (pos + 2 >= len || !is_word_char(bytes[pos + 2])) {
                    // <s (signed)
                    Some((TokenType::LessThanSigned, 2))
                } else {
                    // <
                    Some((TokenType::LessThan, 1))
                }
            }
            b'!' => {
                if next == b'=' {
                    Some((TokenType::NotEquals, 2))
                } else {
                    Some((TokenType::LogicalNot, 1))
                }
            }
            b'=' => {
                if next == b'=' {
                    Some((TokenType::DoubleEquals, 2))
                } else {
                    Some((TokenType::Equals, 1))
                }
            }
            b'&' => {
                if next == b'&' {
                    Some((TokenType::LogicalAnd, 2))
                } else {
                    Some((TokenType::Ampersand, 1))
                }
            }
            b'|' => {
                if next == b'|' {
                    Some((TokenType::LogicalOr, 2))
                } else {
                    Some((TokenType::Pipe, 1))
                }
            }
            b'/' => {
                // Note: // (comment) is already handled before try_match is called.
                if next == b's' && (pos + 2 >= len || !is_word_char(bytes[pos + 2])) {
                    Some((TokenType::DivideSigned, 2))
                } else {
                    Some((TokenType::Divide, 1))
                }
            }
            b'%' => {
                if next == b's' && (pos + 2 >= len || !is_word_char(bytes[pos + 2])) {
                    Some((TokenType::ModuloSigned, 2))
                } else {
                    Some((TokenType::Modulo, 1))
                }
            }
            b'{' => Some((TokenType::Lbrace, 1)),
            b'}' => Some((TokenType::Rbrace, 1)),
            b'[' => Some((TokenType::Lbracket, 1)),
            b']' => Some((TokenType::Rbracket, 1)),
            b'(' => Some((TokenType::Lparen, 1)),
            b')' => Some((TokenType::Rparen, 1)),
            b';' => Some((TokenType::Semicolon, 1)),
            b':' => Some((TokenType::Colon, 1)),
            b'.' => Some((TokenType::Dot, 1)),
            b'+' => Some((TokenType::Plus, 1)),
            b'-' => Some((TokenType::Minus, 1)),
            b'*' => Some((TokenType::Multiply, 1)),
            b'^' => Some((TokenType::Caret, 1)),
            b'~' => Some((TokenType::Tilde, 1)),
            b'?' => Some((TokenType::Question, 1)),
            b'@' => Some((TokenType::At, 1)),
            b',' => Some((TokenType::Comma, 1)),
            _ => None,
        }
    }
}

impl Default for ISALexer {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    /// Helper: tokenize and return (type, value) pairs.
    fn tok(input: &str) -> Vec<(String, String)> {
        let lexer = ISALexer::new();
        lexer
            .tokenize(input)
            .unwrap()
            .into_iter()
            .map(|t| (t.type_.to_string(), t.value))
            .collect()
    }

    #[test]
    fn test_keywords() {
        let tokens = tok("isa_state mem var assume for if else case when aspect gates ext push sensitive flush cam ctz clz of");
        let types: Vec<&str> = tokens.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(
            types,
            vec![
                "ISA_STATE", "MEM", "VAR", "ASSUME", "FOR", "IF", "ELSE", "CASE", "WHEN",
                "ASPECT", "GATES", "EXT", "PUSH", "SENSITIVE", "FLUSH", "CAM", "CTZ", "CLZ", "OF"
            ]
        );
    }

    #[test]
    fn test_keyword_word_boundary() {
        // "memory" should NOT tokenize as MEM + "ory"
        let tokens = tok("memory");
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0], ("IDENTIFIER".into(), "memory".into()));

        // "format" should be IDENTIFIER, not FOR + mat
        let tokens = tok("format");
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0], ("IDENTIFIER".into(), "format".into()));

        // "iffy" should be IDENTIFIER
        let tokens = tok("iffy");
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0], ("IDENTIFIER".into(), "iffy".into()));
    }

    #[test]
    fn test_fp_types() {
        let tokens = tok("fp16 fp32 fp64 fp128 fp16_res fp32_res fp64_res fp128_res fpcmp_res");
        let types: Vec<&str> = tokens.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(
            types,
            vec![
                "FP_TYPE", "FP_TYPE", "FP_TYPE", "FP_TYPE", "FP_TYPE", "FP_TYPE", "FP_TYPE",
                "FP_TYPE", "FPCMP_RES"
            ]
        );
    }

    #[test]
    fn test_fp_type_not_prefix() {
        // "fp16x" should be an IDENTIFIER, not FP_TYPE
        let tokens = tok("fp16x");
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0], ("IDENTIFIER".into(), "fp16x".into()));
    }

    #[test]
    fn test_identifiers() {
        let tokens = tok("foo _bar baz123 __init");
        let types: Vec<&str> = tokens.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(types, vec!["IDENTIFIER", "IDENTIFIER", "IDENTIFIER", "IDENTIFIER"]);
    }

    #[test]
    fn test_numbers() {
        let tokens = tok("42 0 123");
        assert_eq!(tokens[0], ("NUMBER".into(), "42".into()));
        assert_eq!(tokens[1], ("NUMBER".into(), "0".into()));
        assert_eq!(tokens[2], ("NUMBER".into(), "123".into()));
    }

    #[test]
    fn test_hex_number() {
        let tokens = tok("0xFF 0x0 0xDEAD");
        assert_eq!(tokens[0], ("HEX_NUMBER".into(), "0xFF".into()));
        assert_eq!(tokens[1], ("HEX_NUMBER".into(), "0x0".into()));
        assert_eq!(tokens[2], ("HEX_NUMBER".into(), "0xDEAD".into()));
    }

    #[test]
    fn test_verilog_literals() {
        let tokens = tok("32'hFFFF 2'b01 6'd32");
        assert_eq!(
            tokens[0],
            ("VERILOG_HEX_LITERAL".into(), "32'hFFFF".into())
        );
        assert_eq!(tokens[1], ("BINARY_LITERAL".into(), "2'b01".into()));
        assert_eq!(tokens[2], ("DECIMAL_LITERAL".into(), "6'd32".into()));
    }

    #[test]
    fn test_binary_wildcard() {
        let tokens = tok("0b01*1");
        assert_eq!(
            tokens[0],
            ("BINARY_WILDCARD".into(), "0b01*1".into())
        );
    }

    #[test]
    fn test_shifts() {
        let tokens = tok(">>> << >>");
        let types: Vec<&str> = tokens.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(types, vec!["ARITH_RIGHT_SHIFT", "LEFT_SHIFT", "RIGHT_SHIFT"]);
    }

    #[test]
    fn test_comparison_ops() {
        let tokens = tok("!= == <= >= < >");
        let types: Vec<&str> = tokens.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(
            types,
            vec![
                "NOT_EQUALS",
                "DOUBLE_EQUALS",
                "LESS_EQUAL",
                "GREATER_EQUAL",
                "LESS_THAN",
                "GREATER_THAN"
            ]
        );
    }

    #[test]
    fn test_signed_ops() {
        let tokens = tok("<=s >=s <s >s /s %s");
        let types: Vec<&str> = tokens.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(
            types,
            vec![
                "LESS_EQUAL_SIGNED",
                "GREATER_EQUAL_SIGNED",
                "LESS_THAN_SIGNED",
                "GREATER_THAN_SIGNED",
                "DIVIDE_SIGNED",
                "MODULO_SIGNED"
            ]
        );
    }

    #[test]
    fn test_signed_op_not_identifier() {
        // "/something" should be DIVIDE + IDENTIFIER, not DIVIDE_SIGNED
        let tokens = tok("/something");
        assert_eq!(tokens[0].0, "DIVIDE");
        assert_eq!(tokens[1].0, "IDENTIFIER");
    }

    #[test]
    fn test_logical_ops() {
        let tokens = tok("&& || & |");
        let types: Vec<&str> = tokens.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(types, vec!["LOGICAL_AND", "LOGICAL_OR", "AMPERSAND", "PIPE"]);
    }

    #[test]
    fn test_punctuation() {
        let tokens = tok("{ } [ ] ( ) ; : . = + - * / % ^ ~ ! ? @ ,");
        let types: Vec<&str> = tokens.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(
            types,
            vec![
                "LBRACE", "RBRACE", "LBRACKET", "RBRACKET", "LPAREN", "RPAREN",
                "SEMICOLON", "COLON", "DOT", "EQUALS", "PLUS", "MINUS",
                "MULTIPLY", "DIVIDE", "MODULO", "CARET", "TILDE", "LOGICAL_NOT",
                "QUESTION", "AT", "COMMA"
            ]
        );
    }

    #[test]
    fn test_comment_skipped() {
        let tokens = tok("foo // this is a comment\nbar");
        assert_eq!(tokens.len(), 2);
        assert_eq!(tokens[0].1, "foo");
        assert_eq!(tokens[1].1, "bar");
    }

    #[test]
    fn test_whitespace_skipped() {
        let tokens = tok("  foo   bar  ");
        assert_eq!(tokens.len(), 2);
    }

    #[test]
    fn test_line_column_tracking() {
        let lexer = ISALexer::new();
        let tokens = lexer.tokenize("foo bar\n  baz").unwrap();
        assert_eq!(tokens[0].line, 1);
        assert_eq!(tokens[0].column, 1);
        assert_eq!(tokens[1].line, 1);
        assert_eq!(tokens[1].column, 5);
        assert_eq!(tokens[2].line, 2);
        assert_eq!(tokens[2].column, 3);
    }

    #[test]
    fn test_error_on_invalid_char() {
        let lexer = ISALexer::new();
        let result = lexer.tokenize("foo $ bar");
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.contains("line 1"));
        assert!(err.contains("column 5"));
        assert!(err.contains("$"));
    }

    #[test]
    fn test_complex_expression() {
        let tokens = tok("x[31:0] = y + z * 2;");
        let types: Vec<&str> = tokens.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(
            types,
            vec![
                "IDENTIFIER", "LBRACKET", "NUMBER", "COLON", "NUMBER", "RBRACKET",
                "EQUALS", "IDENTIFIER", "PLUS", "IDENTIFIER", "MULTIPLY", "NUMBER",
                "SEMICOLON"
            ]
        );
    }

    #[test]
    fn test_isa_state_declaration() {
        let tokens = tok("isa_state pc[64];");
        let types: Vec<&str> = tokens.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(
            types,
            vec!["ISA_STATE", "IDENTIFIER", "LBRACKET", "NUMBER", "RBRACKET", "SEMICOLON"]
        );
    }

    #[test]
    fn test_empty_input() {
        let tokens = tok("");
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_only_comments() {
        let tokens = tok("// just a comment\n// another comment");
        assert!(tokens.is_empty());
    }

    #[test]
    fn test_display_token() {
        let token = ISAToken {
            type_: TokenType::Identifier,
            value: "foo".to_string(),
            line: 1,
            column: 5,
        };
        assert_eq!(format!("{}", token), "Token(IDENTIFIER, 'foo', 1:5)");
    }
}
