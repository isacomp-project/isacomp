// Re-export from the parser submodule.
// The ISA parser is split into multiple files for maintainability:
//   parser/mod.rs          - ISAParser struct, core methods, preprocessing
//   parser/expressions.rs  - Expression parsing (precedence climbing)
//   parser/declarations.rs - Declaration parsing (isa_state, var, mem, etc.)
//   parser/statements.rs   - Statement parsing (assignment, if, for, case)
//   parser/nodes.rs        - Node creation and expression_to_id

pub use crate::parser::ISAParser;
