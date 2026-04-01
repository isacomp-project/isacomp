import re
from typing import List, Dict, Tuple, Optional, Union
from uuid import uuid4
from .resource_graph import ResourceGraph, Node, Edge


# FP type width mappings
# Value types: just the IEEE 754 format width
# Result types: IEEE format width + 5 flag bits
FP_TYPE_WIDTHS = {
    # Value types (IEEE 754 format)
    'fp16': 16,
    'fp32': 32,
    'fp64': 64,
    'fp128': 128,
    # Result types (value + 5 exception flags)
    'fp16_res': 21,   # 16 + 5
    'fp32_res': 37,   # 32 + 5
    'fp64_res': 69,   # 64 + 5
    'fp128_res': 133, # 128 + 5
    # Comparison result (1-bit bool + 5 exception flags)
    'fpcmp_res': 6,
}

# FP type metadata (for semantic analysis)
FP_TYPE_INFO = {
    'fp16': {'value_bits': 16, 'flag_bits': 0, 'is_result': False, 'format': 'fp16'},
    'fp32': {'value_bits': 32, 'flag_bits': 0, 'is_result': False, 'format': 'fp32'},
    'fp64': {'value_bits': 64, 'flag_bits': 0, 'is_result': False, 'format': 'fp64'},
    'fp128': {'value_bits': 128, 'flag_bits': 0, 'is_result': False, 'format': 'fp128'},
    'fp16_res': {'value_bits': 16, 'flag_bits': 5, 'is_result': True, 'format': 'fp16'},
    'fp32_res': {'value_bits': 32, 'flag_bits': 5, 'is_result': True, 'format': 'fp32'},
    'fp64_res': {'value_bits': 64, 'flag_bits': 5, 'is_result': True, 'format': 'fp64'},
    'fp128_res': {'value_bits': 128, 'flag_bits': 5, 'is_result': True, 'format': 'fp128'},
    'fpcmp_res': {'value_bits': 1, 'flag_bits': 5, 'is_result': True, 'format': 'bool'},
}


class ISAToken:
    def __init__(self, type_: str, value: str, line: int, column: int):
        self.type = type_
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):
        return f"Token({self.type}, '{self.value}', {self.line}:{self.column})"


class ISALexer:
    def __init__(self):
        self.token_patterns = [
            ('COMMENT', r'//.*'),
            ('ISA_STATE', r'isa_state(?![a-zA-Z0-9_])'),
            ('MEM', r'mem(?![a-zA-Z0-9_])'),
            ('VAR', r'var(?![a-zA-Z0-9_])'),
            ('ASSUME', r'assume(?![a-zA-Z0-9_])'),
            ('FOR', r'for(?![a-zA-Z0-9_])'),
            ('IF', r'if(?![a-zA-Z0-9_])'),
            ('ELSE', r'else(?![a-zA-Z0-9_])'),
            ('CASE', r'case(?![a-zA-Z0-9_])'),
            ('WHEN', r'when(?![a-zA-Z0-9_])'),
            ('ASPECT', r'aspect(?![a-zA-Z0-9_])'),
            ('GATES', r'gates(?![a-zA-Z0-9_])'),
            ('EXT', r'ext(?![a-zA-Z0-9_])'),
            ('PUSH', r'push(?![a-zA-Z0-9_])'),
            ('SENSITIVE', r'sensitive(?![a-zA-Z0-9_])'),
            ('FLUSH', r'flush(?![a-zA-Z0-9_])'),
            ('USE', r'use(?![a-zA-Z0-9_])'),  # Orthogon use statement
            ('CAM', r'cam(?![a-zA-Z0-9_])'),  # Content-addressable memory modifier
            ('CTZ', r'ctz(?![a-zA-Z0-9_])'),  # Count trailing zeros builtin
            ('CLZ', r'clz(?![a-zA-Z0-9_])'),  # Count leading zeros builtin
            ('OF', r'of(?![a-zA-Z0-9_])'),  # Match 'of' only if not followed by alphanumeric
            # FP types - must come before IDENTIFIER
            ('FP_TYPE', r'fp(?:16|32|64|128)(?:_res)?(?![a-zA-Z0-9_])'),  # fp16, fp32, fp64, fp128, fp16_res, etc.
            ('FPCMP_RES', r'fpcmp_res(?![a-zA-Z0-9_])'),  # Comparison result type
            ('IDENTIFIER', r'[a-zA-Z_][a-zA-Z0-9_]*'),
            ('VERILOG_HEX_LITERAL', r"\d+'h[0-9a-fA-F]+"),  # Verilog hex literals like 32'hFFFF
            ('BINARY_WILDCARD', r"0b[01*]+"),  # Binary wildcard patterns like 0b0** or 0b1**
            ('BINARY_LITERAL', r"\d+'b[01]+"),  # Verilog binary literals like 2'b0, 16'b1111
            ('DECIMAL_LITERAL', r"\d+'d\d+"),  # Verilog decimal literals like 6'd32, 64'd1
            ('HEX_NUMBER', r'0x[0-9a-fA-F]+'),
            ('NUMBER', r'\d+'),
            ('ARITH_RIGHT_SHIFT', r'>>>'),
            ('LEFT_SHIFT', r'<<'),
            ('RIGHT_SHIFT', r'>>'),
            ('NOT_EQUALS', r'!='),
            ('DOUBLE_EQUALS', r'=='),
            ('LESS_EQUAL_SIGNED', r'<=s'),
            ('GREATER_EQUAL_SIGNED', r'>=s'),
            ('LESS_THAN_SIGNED', r'<s'),
            ('GREATER_THAN_SIGNED', r'>s'),
            ('LESS_EQUAL', r'<='),
            ('GREATER_EQUAL', r'>='),
            ('LESS_THAN', r'<'),
            ('GREATER_THAN', r'>'),
            ('LBRACE', r'\{'),
            ('RBRACE', r'\}'),
            ('LBRACKET', r'\['),
            ('RBRACKET', r'\]'),
            ('LPAREN', r'\('),
            ('RPAREN', r'\)'),
            ('SEMICOLON', r';'),
            ('COLON', r':'),
            ('DOT', r'\.'),
            ('EQUALS', r'='),
            ('PLUS', r'\+'),
            ('MINUS', r'-'),
            ('MULTIPLY', r'\*'),
            ('DIVIDE_SIGNED', r'/s'),
            ('DIVIDE', r'/'),
            ('MODULO_SIGNED', r'%s'),
            ('MODULO', r'%'),
            ('LOGICAL_AND', r'&&'),  # Must come before AMPERSAND
            ('LOGICAL_OR', r'\|\|'),  # Must come before PIPE
            ('AMPERSAND', r'&'),
            ('PIPE', r'\|'),
            ('CARET', r'\^'),
            ('TILDE', r'~'),
            ('LOGICAL_NOT', r'!'),
            ('QUESTION', r'\?'),
            ('AT', r'@'),  # CAM associative lookup operator
            ('COMMA', r','),
            ('WHITESPACE', r'\s+'),
            ('NEWLINE', r'\n'),
        ]
        self.compiled_patterns = [(name, re.compile(pattern)) for name, pattern in self.token_patterns]

    def tokenize(self, text: str) -> List[ISAToken]:
        tokens = []
        lines = text.split('\n')

        for line_num, line in enumerate(lines, 1):
            column = 1
            while column <= len(line):
                matched = False
                for token_type, pattern in self.compiled_patterns:
                    match = pattern.match(line, column - 1)
                    if match:
                        value = match.group(0)
                        if token_type not in ('WHITESPACE', 'COMMENT'):
                            tokens.append(ISAToken(token_type, value, line_num, column))
                        column += len(value)
                        matched = True
                        break

                if not matched:
                    raise ValueError(f"Invalid character at line {line_num}, column {column}: '{line[column-1]}'")

        return tokens


class ISAParser:
    def __init__(self, defines: dict = None):
        self.lexer = ISALexer()
        self.tokens = []
        self.current = 0
        self.current_file = None  # Track current file for aspect resolution
        self.defines = defines or {}  # Preprocessor defines

    def preprocess(self, filename: str) -> str:
        """
        Run C preprocessor on the file.

        Args:
            filename: Path to the .isa file

        Returns:
            Preprocessed content as string
        """
        import subprocess
        import tempfile
        import os

        # Build cpp command with defines
        cmd = ['cpp', '-P']  # -P suppresses line markers

        # Add the file's directory and parent directories to the include path
        # so #include "relative/path.isa" works from subdirectories
        file_dir = os.path.dirname(os.path.abspath(filename))
        if file_dir:
            cmd.append(f'-I{file_dir}')
            parent_dir = os.path.dirname(file_dir)
            if parent_dir and parent_dir != file_dir:
                cmd.append(f'-I{parent_dir}')

        for key, value in self.defines.items():
            if value is None or value == '':
                cmd.append(f'-D{key}')
            else:
                cmd.append(f'-D{key}={value}')
        cmd.append(filename)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Preprocessor error: {e.stderr}")
        except FileNotFoundError:
            # cpp not available, fall back to reading file directly
            with open(filename, 'r') as f:
                return f.read()

    def parse_file(self, filename: str, preprocess: bool = True, existing_graph: ResourceGraph = None) -> ResourceGraph:
        """
        Parse an ISA file.

        Args:
            filename: Path to the .isa file
            preprocess: Whether to run C preprocessor (default True)
            existing_graph: Optional existing graph to parse into (for aspects)

        Returns:
            Parsed ResourceGraph
        """
        if preprocess:
            content = self.preprocess(filename)
        else:
            with open(filename, 'r') as f:
                content = f.read()

        self.current_file = filename
        # When parsing into existing graph (for aspects), skip aspect merging
        skip_merge = existing_graph is not None
        return self.parse(content, existing_graph, skip_aspect_merge=skip_merge)

    def parse(self, text: str, existing_graph: ResourceGraph = None, skip_aspect_merge: bool = False) -> ResourceGraph:
        self.tokens = self.lexer.tokenize(text)
        self.current = 0
        graph = existing_graph if existing_graph is not None else ResourceGraph()
        self.loop_vars = {}  # Track loop variables and their current values
        self.enable_condition = None  # Track current enable condition for conditional writes
        self.register_aliases = {}  # Track register aliases: alias_name -> parent_expression
        # Track most recent node for each variable after assignments (for variable-length instructions).
        # When parsing into an existing graph (for aspects), inherit intermediate values
        # so aspect code can see in-cycle assignments that preceded the aspect declaration.
        if existing_graph is not None and hasattr(existing_graph, '_intermediate_values'):
            self.intermediate_values = dict(existing_graph._intermediate_values)
        else:
            self.intermediate_values = {}
        # Set current_graph so expression_to_id can look up intermediate values
        # Note: The expression_to_id method has been modified to NOT add _rd/_wr suffixes
        # during initial parsing - it only uses current_graph for intermediate value lookups
        self.current_graph = graph

        while not self.is_at_end():
            if self.check('EXT') or self.check('PUSH') or self.check('SENSITIVE'):
                # Handle ext/push/sensitive modifiers for isa_state
                self.parse_isa_state_declaration(graph)
            elif self.check('ISA_STATE'):
                self.parse_isa_state_declaration(graph)
            elif self.check('MEM'):
                self.parse_mem_declaration(graph)
            elif self.check('VAR'):
                self.parse_var_declaration(graph)
            elif self.check('FP_TYPE') or self.check('FPCMP_RES'):
                self.parse_fp_var_declaration(graph)
            elif self.check('ASSUME'):
                self.parse_assume_statement(graph)
            elif self.check('ASPECT'):
                self.parse_aspect_declaration(graph)
            elif self.check('FOR'):
                self.parse_for_loop(graph)
            elif self.check('IF'):
                self.parse_if_statement(graph)
            elif self.check('CASE'):
                self.parse_case_statement(graph)
            elif self.check('FLUSH'):
                self.parse_flush_statement(graph)
            elif self.check('USE'):
                self.parse_use_statement(graph)
            elif self.check('IDENTIFIER'):
                self.parse_assignment(graph)
            else:
                self.advance()

        # Note: orthogon expansion now happens inline during parsing
        # (in parse_use_statement) so that provides outputs are available
        # as intermediate values for subsequent instruction body statements.

        # Merge aspects if any are declared (unless we're already merging)
        if graph.aspect_declarations and not skip_aspect_merge:
            from .aspect_merger import merge_aspects
            merge_aspects(graph, self.current_file)

        # Infer mem widths after parsing complete
        from opt.memory.mem_width_inference import infer_mem_widths
        infer_mem_widths(graph)

        # Classify architectural state based on usage patterns
        graph.classify_architectural_state()
        return graph

    def parse_isa_state_declaration(self, graph: ResourceGraph):
        # Check for ext/push/sensitive modifiers
        is_external = False
        is_push = False
        is_sensitive = False

        if self.check('EXT'):
            self.consume('EXT', "Expected 'ext'")
            is_external = True
            # Check for optional 'push' modifier after 'ext'
            if self.check('PUSH'):
                self.consume('PUSH', "Expected 'push'")
                is_push = True
        elif self.check('SENSITIVE'):
            self.consume('SENSITIVE', "Expected 'sensitive'")
            is_sensitive = True

        # Validate: can't be both sensitive and push
        if is_sensitive and is_push:
            raise ValueError("State cannot be both 'sensitive' and 'push'")

        # Validate: can't be both sensitive and external
        if is_sensitive and is_external:
            raise ValueError("State cannot be both 'sensitive' and 'ext' (they serve different purposes)")

        self.consume('ISA_STATE', "Expected 'isa_state'")

        # Check for 'cam' modifier for content-addressable memory
        is_cam = False
        if self.check('CAM'):
            self.consume('CAM', "Expected 'cam'")
            is_cam = True

        name = self.consume('IDENTIFIER', "Expected identifier").value

        if is_cam:
            # CAM syntax: isa_state cam name[tag_width]@[way_bits][set_bits];
            # Parse tag width: [high:low]
            if not self.check('LBRACKET'):
                raise ValueError(f"CAM '{name}' must specify tag width: isa_state cam {name}[tag_hi:tag_lo]@[way_bits][set_bits];")
            tag_dimension = self.parse_array_dimension()
            tag_width = tag_dimension[0] - tag_dimension[1] + 1

            # Expect @ for associative marker
            if not self.check('AT'):
                raise ValueError(f"CAM '{name}' must have @ marker: isa_state cam {name}[tag_width]@[way_bits][set_bits];")
            self.consume('AT', "Expected '@'")

            # Parse way bits: [high:low] or [] for direct-mapped (1 way)
            if not self.check('LBRACKET'):
                raise ValueError(f"CAM '{name}' must specify ways: @[way_bits] or @[] for direct-mapped")
            self.consume('LBRACKET', "Expected '['")

            if self.check('RBRACKET'):
                # Empty @[] means 1 way (direct-mapped)
                self.consume('RBRACKET', "Expected ']'")
                way_bits = 0
                num_ways = 1
            else:
                # Parse way dimension
                way_high = self.parse_expression()
                self.consume('COLON', "Expected ':'")
                way_low = self.parse_expression()
                self.consume('RBRACKET', "Expected ']'")
                # Extract literal values
                if way_high['type'] != 'literal' or way_low['type'] != 'literal':
                    raise ValueError(f"CAM '{name}' way dimension must be literal values")
                way_bits = way_high['value'] - way_low['value'] + 1
                num_ways = 1 << way_bits

            # Parse set bits: [high:low] or [] for fully associative (1 set)
            if not self.check('LBRACKET'):
                raise ValueError(f"CAM '{name}' must specify sets: [set_bits] or [] for fully associative")
            self.consume('LBRACKET', "Expected '['")

            if self.check('RBRACKET'):
                # Empty [] means 1 set (fully associative)
                self.consume('RBRACKET', "Expected ']'")
                set_bits = 0
                num_sets = 1
            else:
                # Parse set dimension
                set_high = self.parse_expression()
                self.consume('COLON', "Expected ':'")
                set_low = self.parse_expression()
                self.consume('RBRACKET', "Expected ']'")
                # Extract literal values
                if set_high['type'] != 'literal' or set_low['type'] != 'literal':
                    raise ValueError(f"CAM '{name}' set dimension must be literal values")
                set_bits = set_high['value'] - set_low['value'] + 1
                num_sets = 1 << set_bits

            self.consume('SEMICOLON', "Expected ';'")

            # Total entries = ways * sets
            total_entries = num_ways * num_sets

            # Store CAM info for later use in expressions and codegen
            cam_info = {
                'tag_width': tag_width,
                'tag_dimension': tag_dimension,
                'way_bits': way_bits,
                'num_ways': num_ways,
                'set_bits': set_bits,
                'num_sets': num_sets,
                'total_entries': total_entries,
            }

            # Register the CAM for lookup during expression parsing
            if not hasattr(self, 'cam_declarations'):
                self.cam_declarations = {}
            self.cam_declarations[name] = cam_info

            # Create node for CAM state
            # The underlying storage is tag_width bits × total_entries
            node_data = {
                'type': 'isa_state cam',
                'name': name,
                'display_name': name,
                'bit_width': tag_width,
                'tag_width': tag_width,
                'tag_dimension': tag_dimension,
                'way_bits': way_bits,
                'num_ways': num_ways,
                'set_bits': set_bits,
                'num_sets': num_sets,
                'total_entries': total_entries,
                'array_depth': total_entries,
                'is_memory': True,
                'is_cam': True,
                'is_external': is_external,
                'is_push': is_push,
                'is_sensitive': is_sensitive,
            }

            node = Node(name, node_data, is_arch_state=True, from_isa_spec=True)
            graph.add_node(node)
            return

        # Regular isa_state parsing (non-CAM)
        # Parse array dimensions
        dimensions = []
        while self.check('LBRACKET'):
            dimensions.append(self.parse_array_dimension())

        # Check for register aliasing with 'of' keyword
        if self.check('OF'):
            self.consume('OF', "Expected 'of'")
            # Parse the parent register reference (e.g., xregs[0][7:0])
            alias_parent = self.parse_expression()

            # Check if this contains a wildcard index
            has_wildcard = self._expression_has_wildcard(alias_parent)

            self.consume('SEMICOLON', "Expected ';'")

            # Store the alias mapping and don't create a node
            if has_wildcard:
                # This is a wildcard array alias (e.g., lregs[1:0] of xregs[0b0**][7:0])
                # Store both the pattern and the dimension info
                self.register_aliases[name] = {
                    'type': 'wildcard_array',
                    'parent_expr': alias_parent,
                    'dimensions': dimensions  # The lregs dimensions [1:0]
                }
            else:
                # Simple scalar alias (e.g., AL of AX[7:0])
                self.register_aliases[name] = alias_parent
            return

        self.consume('SEMICOLON', "Expected ';'")

        # Create node for ISA state
        # Calculate bit width and depth information
        bit_width = dimensions[0][0] - dimensions[0][1] + 1 if dimensions else 1
        dimension_count = len(dimensions)
        array_depth = None

        if dimension_count > 1:
            # Multi-dimensional array - second dimension gives array size
            array_depth = dimensions[1][0] - dimensions[1][1] + 1

        node_data = {
            'type': 'isa_state',
            'name': name,
            'display_name': name,
            'dimensions': dimensions,
            'dimension_count': dimension_count,
            'bit_width': bit_width,
            'array_depth': array_depth,
            'is_memory': dimension_count > 1,
            'is_external': is_external,
            'is_push': is_push,
            'is_sensitive': is_sensitive,
        }

        # For RISC-V instruction and data memory, use word addressing
        # (addresses are word indices, not byte addresses)
        if name in ['imem', 'dmem'] and dimension_count > 1:
            node_data['address_unit'] = 'word'
        # All isa_state declarations are architectural state
        # This includes: memories, register files, and scalar state like pc, flags, segment registers
        node = Node(name, node_data, is_arch_state=True, from_isa_spec=True)
        graph.add_node(node)

    def parse_mem_declaration(self, graph: ResourceGraph):
        """Parse mem declaration: mem name[addr_range];

        Unlike isa_state, mem doesn't require upfront data width.
        Width is inferred from access patterns.
        """
        self.consume('MEM', "Expected 'mem'")
        name = self.consume('IDENTIFIER', "Expected identifier").value

        # Parse address dimension only
        addr_dimension = None
        if self.check('LBRACKET'):
            addr_dimension = self.parse_array_dimension()
        else:
            raise ValueError(f"Memory '{name}' must specify address range: mem {name}[addr_bits];")

        self.consume('SEMICOLON', "Expected ';'")

        # Create node for memory with width TBD
        addr_bits = addr_dimension[0] - addr_dimension[1] + 1

        node_data = {
            'type': 'isa_state mem',          # Prefix with isa_state to indicate it's ISA state
            'name': name,
            'display_name': name,
            'bit_width': None,                # To be inferred
            'addr_bits': addr_bits,
            'array_depth': addr_bits,         # Store addr_bits as array_depth for verilog_generator
            'addr_dimension': addr_dimension,
            'is_memory': True,
            'width_inferred': True,           # Flag indicating width inference needed
            'access_widths': []               # Track all observed access widths
        }

        # Always mark as architectural state (memories are always arch state)
        node = Node(name, node_data, is_arch_state=True, from_isa_spec=True)
        graph.add_node(node)

    def parse_var_declaration(self, graph: ResourceGraph):
        self.consume('VAR', "Expected 'var'")

        # Parse variable name first (like isa_state), then require bit range
        # New syntax: var name[high:low];
        name = self.consume('IDENTIFIER', "Expected identifier").value

        # Require bit range after name: var name[31:0];
        if not self.check('LBRACKET'):
            raise ValueError(
                f"Variable '{name}' must have an explicit width. "
                f"Use: var {name}[high:low];"
            )

        bit_range = self.parse_array_dimension()
        bit_width = bit_range[0] - bit_range[1] + 1

        self.consume('SEMICOLON', "Expected ';'")

        # Create node for variable with explicit width
        # Mark as from_isa_spec since it's explicitly declared by the user
        node_data = {
            'type': 'var',
            'name': name,
            'display_name': name,
            'width': bit_width,
            'bit_width': bit_width,
            'bit_range': bit_range,
            'width_explicit': True  # Always true now since width is required
        }
        node = Node(name, node_data, from_isa_spec=True)
        graph.add_node(node)

    def parse_fp_var_declaration(self, graph: ResourceGraph):
        """Parse FP typed variable declaration: fp32 name; or fp32 a, b, c;"""
        # Get the FP type token
        if self.check('FP_TYPE'):
            fp_type = self.consume('FP_TYPE', "Expected FP type").value
        else:
            fp_type = self.consume('FPCMP_RES', "Expected fpcmp_res").value

        # Look up type info
        if fp_type not in FP_TYPE_WIDTHS:
            raise ValueError(f"Unknown FP type: {fp_type}")

        bit_width = FP_TYPE_WIDTHS[fp_type]
        type_info = FP_TYPE_INFO[fp_type]

        # Parse one or more variable names (comma-separated)
        names = []
        names.append(self.consume('IDENTIFIER', "Expected variable name").value)

        while self.check('COMMA'):
            self.consume('COMMA', "Expected ','")
            names.append(self.consume('IDENTIFIER', "Expected variable name").value)

        self.consume('SEMICOLON', "Expected ';'")

        # Create nodes for each variable
        for name in names:
            node_data = {
                'type': 'fp_var',
                'name': name,
                'display_name': name,
                'width': bit_width,
                'bit_width': bit_width,
                'bit_range': (bit_width - 1, 0),
                'width_explicit': True,
                'fp_type': fp_type,
                'fp_type_info': type_info,
                'value_type': 'floating_point',
            }
            node = Node(name, node_data, from_isa_spec=True)
            graph.add_node(node)

    def parse_assume_statement(self, graph: ResourceGraph):
        self.consume('ASSUME', "Expected 'assume'")

        # Parse the assume expression using the standard expression parser.
        # This produces a proper AST (typically a binary_op with == or !=).
        assume_expr = self.parse_expression()

        self.consume('SEMICOLON', "Expected ';'")

        # Store the parsed assume expression in the graph for the merger to consume.
        # This eliminates the need for the merger to re-parse the raw file text.
        if not hasattr(graph, 'assume_expressions'):
            graph.assume_expressions = []
        graph.assume_expressions.append(assume_expr)

    def parse_flush_statement(self, graph: ResourceGraph):
        """Parse flush statement: flush <cache_name>;

        Creates a flush signal node in the graph with an edge to a placeholder
        target. The cache optimization will detect this placeholder and wire
        the flush signal to the appropriate cache when it is created.

        The flush signal is driven by a constant 1, which the graph merger
        will AND with the instruction's enable signal. This ensures the flush
        only occurs when this specific instruction is executing.

        This enables ISA-level cache flush semantics (e.g., fence.i, sfence.vma)
        to connect to microarchitectural cache implementations.
        """
        self.consume('FLUSH', "Expected 'flush'")
        cache_name = self.consume('IDENTIFIER', "Expected cache name").value
        self.consume('SEMICOLON', "Expected ';'")

        # Create a constant 1 node - the flush is active when this instruction executes
        # The merger will AND this with the instruction's enable signal
        const_node_id = f"flush_{cache_name}_const"
        const_node = Node(
            node_id=const_node_id,
            data={
                'type': 'literal',
                'value': 1,
                'bit_width': 1,
                'display_name': f"Flush {cache_name} const",
            }
        )
        graph.add_node(const_node)

        # Create flush signal node as a var - this gets assigned the constant
        # and the merger will properly gate it with the instruction enable
        flush_node_id = f"flush_{cache_name}"
        flush_node = Node(
            node_id=flush_node_id,
            data={
                'type': 'var',
                'name': flush_node_id,
                'display_name': f"Flush {cache_name}",
                'bit_width': 1,
                'is_flush_trigger': True,
                'target_cache': cache_name,
            }
        )
        graph.add_node(flush_node)

        # Edge: const 1 -> flush signal (assignment)
        # This creates: flush_icache = 1 in this instruction's context
        # The merger will gate this with the instruction enable (fence_i_enable)
        assign_edge = Edge(
            source=const_node,
            target=flush_node,
            data={'type': 'assignment'}
        )
        graph.add_edge(assign_edge)

        # Create a placeholder target node - this marks where the cache
        # optimization should wire the flush signal. The placeholder
        # will be replaced with an actual cache connection.
        placeholder_id = f"{cache_name}_flush_target"
        placeholder_node = Node(
            node_id=placeholder_id,
            data={
                'type': 'flush_target_placeholder',
                'cache_name': cache_name,
                'awaiting_cache': True,
                'display_name': f"{cache_name} flush target (placeholder)",
            }
        )
        graph.add_node(placeholder_node)

        # Create edge from flush signal to placeholder
        # The 'untied' marker indicates this edge needs to be connected
        # to an actual cache during the cache optimization phase
        flush_edge = Edge(
            source=flush_node,
            target=placeholder_node,
            data={
                'type': 'cache_flush',
                'target_cache': cache_name,
                'untied': True,
            }
        )
        graph.add_edge(flush_edge)

    def parse_aspect_declaration(self, graph: ResourceGraph):
        """Parse aspect declaration: aspect file.isa gates state1, state2:priority, ...;

        States can optionally have a priority annotation (state:priority).
        When multiple aspects gate the same state, all must have priorities.
        Priority 1 is highest (checked first), 2 is lower, etc.
        """
        self.consume('ASPECT', "Expected 'aspect'")

        # Parse the aspect file name (e.g., interrupts.isa or path/to/file.isa)
        # Collect all tokens until we hit 'gates' or ';'
        aspect_file_parts = []
        while not self.check('GATES') and not self.check('SEMICOLON') and not self.is_at_end():
            token = self.peek()
            # Accept identifiers, dots, slashes for file paths
            # Note: COLON is allowed here for Windows-style paths, but won't conflict
            # with priority syntax since that comes after 'gates'
            if token.type in ['IDENTIFIER', 'COLON', 'DOT']:
                aspect_file_parts.append(token.value)
                self.advance()
            elif token.type == 'DIVIDE':  # '/' for path separator
                aspect_file_parts.append(token.value)
                self.advance()
            elif token.type == 'DIVIDE_SIGNED':  # '/s' - handle paths like /source
                # The lexer greedily matches '/s' as DIVIDE_SIGNED
                # In path context, treat as '/' followed by 's'
                aspect_file_parts.append('/')
                aspect_file_parts.append('s')
                self.advance()
            else:
                break

        aspect_file = ''.join(aspect_file_parts)

        # Parse gated states if 'gates' keyword is present
        # Each state can have optional priority: state_name or state_name:priority
        gated_states = []  # States without priority (exclusive access)
        prioritized_states = {}  # state_name -> priority

        if self.check('GATES'):
            self.consume('GATES', "Expected 'gates'")
            # Parse comma-separated list of state names with optional priorities
            state_name, priority = self._parse_gated_state()
            if priority is not None:
                prioritized_states[state_name] = priority
            else:
                gated_states.append(state_name)

            while self.check('COMMA'):
                self.consume('COMMA', "Expected ','")
                state_name, priority = self._parse_gated_state()
                if priority is not None:
                    prioritized_states[state_name] = priority
                else:
                    gated_states.append(state_name)

        self.consume('SEMICOLON', "Expected ';'")

        # Store aspect declaration in graph metadata
        aspect_decl = {
            'file': aspect_file,
            'gated_states': gated_states,
            'prioritized_states': prioritized_states,
            'order': len(graph.aspect_declarations),  # Order for precedence
            # Snapshot intermediate values at this point so the aspect parser
            # sees in-cycle assignments that precede this aspect declaration,
            # but not assignments that follow it.
            'intermediate_values': dict(self.intermediate_values)
        }
        graph.aspect_declarations.append(aspect_decl)

    def _parse_gated_state(self) -> tuple:
        """Parse a gated state with optional priority: 'state_name' or 'state_name:priority'

        Returns:
            (state_name, priority) where priority is None if not specified
        """
        state_name = self.consume('IDENTIFIER', "Expected state name").value
        priority = None

        if self.check('COLON'):
            self.consume('COLON', "Expected ':'")
            priority_token = self.consume('NUMBER', "Expected priority number after ':'")
            priority = int(priority_token.value)
            if priority < 1:
                raise ValueError(f"Priority must be >= 1, got {priority} for state '{state_name}'")

        return (state_name, priority)

    def parse_use_statement(self, graph: ResourceGraph):
        """Parse orthogon use statement: use orthogon_name(selector_expr);

        Expands the orthogon IMMEDIATELY during parsing so that the provides
        output values are available as intermediate values for subsequent
        statements in the instruction body. This ensures that references like
        `data` or `eff_addr` in the instruction body resolve to the per-
        instruction mux output nodes, not to generic shared names.
        """
        self.consume('USE', "Expected 'use'")
        orthogon_name = self.consume('IDENTIFIER', "Expected orthogon name").value
        self.consume('LPAREN', "Expected '('")

        # Parse the selector expression
        selector_expr = self.parse_expression()

        self.consume('RPAREN', "Expected ')'")
        self.consume('SEMICOLON', "Expected ';'")

        # Create a graph node for the selector expression
        selector_node = self.get_or_create_node_for_expression(
            graph, selector_expr, access_mode='read'
        )
        selector_node_id = selector_node.id if hasattr(selector_node, 'id') else str(selector_node)

        # Expand the orthogon immediately into the graph.
        # This creates mux trees for provides/writes and updates
        # self.intermediate_values so the rest of the instruction body
        # sees the muxed output values.
        use_decl = {
            'orthogon_name': orthogon_name,
            'selector_expr': selector_expr,
            'selector_node_id': selector_node_id,
            'intermediate_values': self.intermediate_values,
        }

        from .orthogon_merger import OrthogonMerger
        merger = OrthogonMerger(graph, getattr(self, 'current_file', None))
        merger.expand_use(use_decl, intermediate_values=self.intermediate_values)

        # Record the use for metadata purposes (not for deferred expansion)
        if not hasattr(graph, 'orthogon_uses'):
            graph.orthogon_uses = []
        graph.orthogon_uses.append(use_decl)

    def parse_for_loop(self, graph: ResourceGraph):
        """Parse and unroll a for loop. Supports for(var; start; condition; increment) { body }"""
        self.consume('FOR', "Expected 'for'")
        self.consume('LPAREN', "Expected '('")

        # Parse loop variable
        loop_var = self.consume('IDENTIFIER', "Expected loop variable").value

        # Support "var; start;" syntax
        # Syntax: for(var; start; ...)
        self.consume('SEMICOLON', "Expected ';'")
        start_value = self.parse_loop_value()
        self.consume('SEMICOLON', "Expected ';'")

        # Parse condition (e.g., <4)
        condition_op = None
        if self.check('LESS_THAN'):
            condition_op = '<'
            self.advance()
        elif self.check('GREATER_THAN'):
            condition_op = '>'
            self.advance()
        else:
            raise ValueError(f"Expected comparison operator in for loop condition")

        condition_value = self.parse_loop_value()
        self.consume('SEMICOLON', "Expected ';'")

        # Parse increment (e.g., +1 or -1)
        increment_op = None
        if self.check('PLUS'):
            increment_op = '+'
            self.advance()
        elif self.check('MINUS'):
            increment_op = '-'
            self.advance()
        else:
            raise ValueError(f"Expected '+' or '-' in for loop increment")

        increment_value = self.parse_loop_value()
        self.consume('RPAREN', "Expected ')'")

        # Parse loop body
        self.consume('LBRACE', "Expected '{'")

        # Collect tokens in the loop body
        body_start = self.current
        brace_count = 1
        while brace_count > 0 and not self.is_at_end():
            if self.check('LBRACE'):
                brace_count += 1
            elif self.check('RBRACE'):
                brace_count -= 1
            if brace_count > 0:
                self.advance()

        body_end = self.current
        self.consume('RBRACE', "Expected '}'")

        # Unroll the loop
        self.unroll_loop(graph, loop_var, start_value, condition_op,
                        condition_value, increment_op, increment_value,
                        body_start, body_end)

    def parse_loop_value(self) -> int:
        """Parse a simple integer value in loop syntax"""
        if self.check('NUMBER'):
            return int(self.advance().value)
        elif self.check('HEX_NUMBER'):
            return int(self.advance().value, 16)
        else:
            raise ValueError(f"Expected numeric value in for loop")

    def can_evaluate(self, expr: Dict) -> bool:
        """Check if an expression can be evaluated to a constant"""
        if expr['type'] == 'literal':
            return True
        elif expr['type'] == 'sized_literal':
            return True
        elif expr['type'] == 'binary_op':
            return self.can_evaluate(expr['left']) and self.can_evaluate(expr['right'])
        elif expr['type'] == 'identifier':
            # Can evaluate if it's a loop variable
            return expr['name'] in self.loop_vars
        return False

    def evaluate_expression(self, expr: Dict) -> int:
        """Evaluate an expression to an integer value"""
        if expr['type'] == 'literal':
            return expr['value']
        elif expr['type'] == 'sized_literal':
            return expr['value']
        elif expr['type'] == 'identifier':
            if expr['name'] in self.loop_vars:
                return self.loop_vars[expr['name']]
            raise ValueError(f"Cannot evaluate identifier: {expr['name']}")
        elif expr['type'] == 'binary_op':
            left = self.evaluate_expression(expr['left'])
            right = self.evaluate_expression(expr['right'])
            op = expr['operator']
            if op == '+':
                return left + right
            elif op == '-':
                return left - right
            elif op == '*':
                return left * right
            elif op == '/':
                return left // right  # Integer division (unsigned)
            elif op == '/s':
                # Signed integer division (truncated toward zero)
                # int() truncates toward zero, unlike Python's // which floors
                return int(left / right) if right != 0 else 0
            elif op == '%':
                return left % right  # Unsigned modulo
            elif op == '%s':
                # Signed remainder (sign matches dividend)
                # Must use truncated division quotient, not Python's floored //
                if right == 0:
                    return left
                signed_quot = int(left / right)
                return left - signed_quot * right
            elif op == '<<':
                return left << right
            elif op == '>>':
                return left >> right
            elif op == '>>>':
                # Arithmetic right shift - need to handle sign extension
                # For now, use Python's >> which is arithmetic for negative numbers
                return left >> right
            elif op == '&':
                return left & right
            elif op == '|':
                return left | right
            elif op == '^':
                return left ^ right
            elif op == '==':
                return 1 if left == right else 0
            elif op == '!=':
                return 1 if left != right else 0
            elif op == '<':
                return 1 if left < right else 0
            elif op == '>':
                return 1 if left > right else 0
            elif op == '<=':
                return 1 if left <= right else 0
            elif op == '>=':
                return 1 if left >= right else 0
            else:
                raise ValueError(f"Unknown operator: {op}")
        else:
            raise ValueError(f"Cannot evaluate expression type: {expr['type']}")

    def unroll_loop(self, graph: ResourceGraph, loop_var: str, start: int,
                   condition_op: str, condition_value: int, increment_op: str,
                   increment_value: int, body_start: int, body_end: int):
        """Unroll a for loop by executing the body for each iteration"""

        # Save current position
        saved_pos = self.current

        # Calculate iteration values
        current_val = start
        iterations = []

        if condition_op == '<':
            while current_val < condition_value:
                iterations.append(current_val)
                if increment_op == '+':
                    current_val += increment_value
                else:
                    current_val -= increment_value
        elif condition_op == '>':
            while current_val > condition_value:
                iterations.append(current_val)
                if increment_op == '+':
                    current_val += increment_value
                else:
                    current_val -= increment_value

        # Execute loop body for each iteration
        for iteration_value in iterations:
            # Set loop variable value
            self.loop_vars[loop_var] = iteration_value

            # Reset position to start of loop body
            self.current = body_start

            # Parse loop body with substituted loop variable
            self._parse_body_statements(graph, body_end)

        # Clear loop variable
        if loop_var in self.loop_vars:
            del self.loop_vars[loop_var]

        # Restore position
        self.current = saved_pos

    def _parse_body_statements(self, graph: ResourceGraph, body_end: int,
                                collect_assignments: Optional[List[Dict]] = None):
        """
        Parse statements within a body (if/else/for body) up to body_end position.

        Args:
            graph: The ResourceGraph to add nodes/edges to
            body_end: Token position where the body ends
            collect_assignments: If provided, assignments are collected into this list
                                instead of being parsed normally. Used for runtime
                                conditionals that need to create ternary expressions.
        """
        while self.current < body_end:
            if self.check('IDENTIFIER'):
                if collect_assignments is not None:
                    # Collect assignment for later ternary creation
                    left_expr = self.parse_expression()
                    self.consume('EQUALS', "Expected '='")
                    right_expr = self.parse_expression()
                    self.consume('SEMICOLON', "Expected ';'")
                    collect_assignments.append({'left': left_expr, 'right': right_expr})
                else:
                    self.parse_assignment(graph)
            elif self.check('IF'):
                self.parse_if_statement(graph)
            elif self.check('FOR'):
                self.parse_for_loop(graph)
            elif self.check('CASE'):
                self.parse_case_statement(graph)
            elif self.check('VAR'):
                self.parse_var_declaration(graph)
            else:
                self.advance()

    def parse_if_statement(self, graph: ResourceGraph):
        """Parse an if statement: if (condition) { body } [else { else_body }]"""
        self.consume('IF', "Expected 'if'")
        self.consume('LPAREN', "Expected '('")

        # Parse the condition
        condition_expr = self.parse_expression()

        self.consume('RPAREN', "Expected ')'")
        self.consume('LBRACE', "Expected '{'")

        # Collect tokens in the if body
        body_start = self.current
        brace_count = 1
        while brace_count > 0 and not self.is_at_end():
            if self.check('LBRACE'):
                brace_count += 1
            elif self.check('RBRACE'):
                brace_count -= 1
            if brace_count > 0:
                self.advance()

        body_end = self.current
        self.consume('RBRACE', "Expected '}'")

        # Check for else clause
        else_body_start = None
        else_body_end = None
        if self.check('ELSE'):
            self.advance()  # consume 'else'
            self.consume('LBRACE', "Expected '{'")
            else_body_start = self.current
            brace_count = 1
            while brace_count > 0 and not self.is_at_end():
                if self.check('LBRACE'):
                    brace_count += 1
                elif self.check('RBRACE'):
                    brace_count -= 1
                if brace_count > 0:
                    self.advance()
            else_body_end = self.current
            self.consume('RBRACE', "Expected '}'")

        # Check if we can evaluate the condition at parse time
        if self.can_evaluate(condition_expr):
            condition_value = self.evaluate_expression(condition_expr)

            if condition_value != 0:  # Non-zero means true - execute if body
                saved_pos = self.current
                self.current = body_start
                self._parse_body_statements(graph, body_end)
                self.current = saved_pos
            elif else_body_start is not None:  # Zero means false - execute else body if present
                saved_pos = self.current
                self.current = else_body_start
                self._parse_body_statements(graph, else_body_end)
                self.current = saved_pos
        else:
            # Cannot evaluate at parse time - need to create conditional muxes
            # For simple if-else with matching assignments, convert to ternary:
            # if (cond) { x = a; } else { x = b; }  =>  x = cond ? a : b;
            saved_pos = self.current

            # Collect assignments from if body
            if_assignments = []
            self.current = body_start
            self._parse_body_statements(graph, body_end, collect_assignments=if_assignments)

            # Collect assignments from else body
            else_assignments = []
            if else_body_start is not None:
                self.current = else_body_start
                self._parse_body_statements(graph, else_body_end, collect_assignments=else_assignments)

            # Match if/else assignments by target and create ternary muxes
            # or conditional writes (for if-only without else).
            else_by_target = {}
            for ea in else_assignments:
                left_str = self._expr_to_string(ea['left'])
                else_by_target[left_str] = ea['right']

            for ia in if_assignments:
                left_str = self._expr_to_string(ia['left'])
                if left_str in else_by_target:
                    # Both if and else assign to the same target:
                    # synthesize target = condition ? if_value : else_value
                    ternary_expr = {
                        'type': 'ternary_op',
                        'condition': condition_expr,
                        'if_true': ia['right'],
                        'if_false': else_by_target[left_str]
                    }
                    # Use the standard assignment path through get_or_create_node
                    left_node = self.get_or_create_node_for_expression(
                        graph, ia['left'], access_mode='write'
                    )
                    right_node = self.get_or_create_node_for_expression(
                        graph, ternary_expr, access_mode='read'
                    )
                    edge = Edge(right_node, left_node, data={
                        'type': 'assignment',
                        'left': ia['left'],
                        'right': ternary_expr
                    })
                    graph.add_edge(edge)
                else:
                    # Only the if branch assigns — use the condition as a write enable.
                    # This is equivalent to: target when (condition) = value;
                    left_node = self.get_or_create_node_for_expression(
                        graph, ia['left'], access_mode='write', enable_expr=condition_expr
                    )
                    right_node = self.get_or_create_node_for_expression(
                        graph, ia['right'], access_mode='read'
                    )
                    edge = Edge(right_node, left_node, data={
                        'type': 'assignment',
                        'left': ia['left'],
                        'right': ia['right'],
                        'enable': condition_expr
                    })
                    graph.add_edge(edge)

            # Handle else-only assignments (targets in else but not in if)
            if_targets = {self._expr_to_string(ia['left']) for ia in if_assignments}
            for ea in else_assignments:
                left_str = self._expr_to_string(ea['left'])
                if left_str not in if_targets:
                    # Only the else branch assigns — use NOT(condition) as write enable
                    neg_condition = {
                        'type': 'unary_op',
                        'operator': '!',
                        'operand': condition_expr
                    }
                    left_node = self.get_or_create_node_for_expression(
                        graph, ea['left'], access_mode='write', enable_expr=neg_condition
                    )
                    right_node = self.get_or_create_node_for_expression(
                        graph, ea['right'], access_mode='read'
                    )
                    edge = Edge(right_node, left_node, data={
                        'type': 'assignment',
                        'left': ea['left'],
                        'right': ea['right'],
                        'enable': neg_condition
                    })
                    graph.add_edge(edge)

            self.current = saved_pos

    def _expr_to_string(self, expr: Dict) -> str:
        """Convert an expression to a string for target matching in if/else bodies."""
        if expr is None:
            return ''
        expr_type = expr.get('type', '')
        if expr_type == 'identifier':
            return expr.get('name', '')
        elif expr_type == 'literal':
            return str(expr.get('value', 0))
        elif expr_type == 'sized_literal':
            fmt = {'bin': 'b', 'hex': 'h', 'dec': 'd'}.get(expr.get('format', 'bin'), 'b')
            return f"{expr.get('width', 0)}'{fmt}{expr.get('original_digits', '')}"
        elif expr_type == 'bit_slice':
            target = expr.get('target', {})
            high, low = expr.get('range', ('', ''))
            return f"{self._expr_to_string(target)}[{high}:{low}]"
        elif expr_type == 'array_access':
            return f"{self._expr_to_string(expr.get('target', {}))}[{self._expr_to_string(expr.get('index', {}))}]"
        elif expr_type == 'binary_op':
            return f"({self._expr_to_string(expr.get('left', {}))} {expr.get('operator', '')} {self._expr_to_string(expr.get('right', {}))})"
        else:
            return str(expr)

    def _connect_expr_sources(self, graph: ResourceGraph, expr: Dict, target_node: Node):
        """Add edges from expression source nodes to target node."""
        if expr is None:
            return
        expr_type = expr.get('type', '')
        if expr_type == 'identifier':
            name = expr.get('name', '')
            source_node = graph.nodes.get(name)
            if source_node is None:
                source_node = graph.nodes.get(f'{name}_rd')
            if source_node:
                edge = Edge(source_node, target_node, data={'type': 'operand'})
                graph.add_edge(edge)
        elif expr_type in ['binary_op', 'ternary_op']:
            self._connect_expr_sources(graph, expr.get('left'), target_node)
            self._connect_expr_sources(graph, expr.get('right'), target_node)
            self._connect_expr_sources(graph, expr.get('condition'), target_node)
            self._connect_expr_sources(graph, expr.get('if_true'), target_node)
            self._connect_expr_sources(graph, expr.get('if_false'), target_node)
        elif expr_type == 'bit_slice':
            self._connect_expr_sources(graph, expr.get('target', expr.get('operand')), target_node)
        elif expr_type == 'array_access':
            self._connect_expr_sources(graph, expr.get('target'), target_node)
            self._connect_expr_sources(graph, expr.get('index'), target_node)

    def parse_case_statement(self, graph: ResourceGraph):
        """Parse a case statement: case (selector) { value1: stmt1; value2: stmt2; ... }"""
        self.consume('CASE', "Expected 'case'")
        self.consume('LPAREN', "Expected '('")

        # Parse the selector expression
        selector_expr = self.parse_expression()

        self.consume('RPAREN', "Expected ')'")
        self.consume('LBRACE', "Expected '{'")

        # Parse case arms
        case_arms = []
        while not self.check('RBRACE') and not self.is_at_end():
            # Parse case value (could be binary literal, hex, number, etc.)
            case_value = self.parse_expression()
            self.consume('COLON', "Expected ':' after case value")

            # Parse the statement(s) for this case arm
            # Collect tokens until we see another case value or closing brace
            arm_statements = []

            # Parse single assignment statement
            if self.check('IDENTIFIER'):
                left_side = self.parse_expression()
                self.consume('EQUALS', "Expected '='")
                right_side = self.parse_expression()
                self.consume('SEMICOLON', "Expected ';'")
                arm_statements.append({
                    'left': left_side,
                    'right': right_side
                })

            case_arms.append({
                'value': case_value,
                'statements': arm_statements
            })

        self.consume('RBRACE', "Expected '}'")

        # Check if selector can be evaluated at parse time
        if self.can_evaluate(selector_expr):
            selector_value = self.evaluate_expression(selector_expr)

            # Find matching case arm and execute it
            for arm in case_arms:
                arm_value = self.evaluate_expression(arm['value']) if self.can_evaluate(arm['value']) else None
                if arm_value is not None and arm_value == selector_value:
                    # Execute statements in this arm
                    for stmt in arm['statements']:
                        left_node = self.get_or_create_node_for_expression(graph, stmt['left'], 'write')
                        right_node = self.get_or_create_node_for_expression(graph, stmt['right'], 'read')
                        edge = Edge(right_node, left_node, data={
                            'type': 'assignment',
                            'left': stmt['left'],
                            'right': stmt['right']
                        })
                        graph.add_edge(edge)
                    break
        else:
            # Cannot evaluate at parse time - generate conditional assignments for all arms
            # Check if all arms target the same simple variable - use nested ternaries
            if len(case_arms) >= 2:
                # Check if all statements in all arms target the same simple variable
                # and each arm has exactly one statement
                all_targets_same = True
                target_vars = set()
                for arm in case_arms:
                    if len(arm['statements']) != 1:
                        all_targets_same = False
                        break
                    stmt = arm['statements'][0]
                    if stmt['left'].get('type') == 'identifier':
                        target_vars.add(stmt['left'].get('name'))
                    else:
                        all_targets_same = False
                        break

                if all_targets_same and len(target_vars) == 1:
                    # Create nested ternary expression
                    # selector == arm0 ? v0 : (selector == arm1 ? v1 : (... : vN))
                    def build_nested_ternary(arms, idx):
                        if idx == len(arms) - 1:
                            # Last arm - just return its value (default case)
                            return arms[idx]['statements'][0]['right']
                        else:
                            condition = {
                                'type': 'binary_op',
                                'operator': '==',
                                'left': selector_expr,
                                'right': arms[idx]['value']
                            }
                            return {
                                'type': 'ternary_op',
                                'condition': condition,
                                'if_true': arms[idx]['statements'][0]['right'],
                                'if_false': build_nested_ternary(arms, idx + 1)
                            }

                    ternary_expr = build_nested_ternary(case_arms, 0)
                    target_expr = case_arms[0]['statements'][0]['left']

                    # Create the assignment with nested ternary as right side
                    left_node = self.get_or_create_node_for_expression(graph, target_expr, 'write')
                    right_node = self.get_or_create_node_for_expression(graph, ternary_expr, 'read')
                    edge = Edge(right_node, left_node, data={
                        'type': 'assignment',
                        'left': target_expr,
                        'right': ternary_expr
                    })
                    graph.add_edge(edge)
                    return

            # Fallback: generate conditional assignments for all arms
            # Each arm becomes a conditional assignment based on the selector
            for arm in case_arms:
                arm_condition = {
                    'type': 'binary_op',
                    'operator': '==',
                    'left': selector_expr,
                    'right': arm['value']
                }
                # Create a node for the condition expression so it can be referenced in Verilog
                condition_node = self.get_or_create_node_for_expression(graph, arm_condition, 'read')

                for stmt in arm['statements']:
                    left_node = self.get_or_create_node_for_expression(
                        graph, stmt['left'], 'write', enable_expr=arm_condition
                    )
                    right_node = self.get_or_create_node_for_expression(graph, stmt['right'], 'read')
                    edge = Edge(right_node, left_node, data={
                        'type': 'assignment',
                        'left': stmt['left'],
                        'right': stmt['right'],
                        'enable': arm_condition
                    })
                    graph.add_edge(edge)

    def parse_assignment(self, graph: ResourceGraph):
        left_side = self.parse_expression()

        # Check for 'when' clause (guarded assignment)
        enable_expr = None
        if self.check('WHEN'):
            self.consume('WHEN', "Expected 'when'")
            self.consume('LPAREN', "Expected '(' after 'when'")
            enable_expr = self.parse_expression()
            self.consume('RPAREN', "Expected ')' after enable condition")

        self.consume('EQUALS', "Expected '='")
        right_side = self.parse_expression()
        self.consume('SEMICOLON', "Expected ';'")

        # Eagerly create nodes for the 'when' condition sub-expressions.
        # Without this, bits referenced only in conditions (e.g., instr[1] for
        # the nullification n-bit) would lack graph nodes, causing the
        # aspect_merger to produce incomplete operand edges when it builds
        # gated-write multiplexer select trees.
        if enable_expr:
            self.get_or_create_node_for_expression(graph, enable_expr, 'read')

        # Create assignment edge
        # Mark left side as write target, right side as read source
        left_node = self.get_or_create_node_for_expression(graph, left_side, access_mode='write', enable_expr=enable_expr)
        right_node = self.get_or_create_node_for_expression(graph, right_side, access_mode='read')

        edge_data = {
            'type': 'assignment',
            'left': left_side,
            'right': right_side
        }
        if enable_expr:
            edge_data['enable'] = enable_expr

        # Tag previous writes to the same isa_state as intermediate (dead)
        # BEFORE adding the new edge, so the new edge is not incorrectly tagged.
        # Marks both unconditional and conditional writes as dead when a new write
        # with the SAME enable condition overwrites them. This prevents OR-mux
        # corruption from multiple conditional writes (e.g., pc when (~exc) = pc + 2
        # appearing multiple times for extension word fetching).
        if left_side.get('type') == 'identifier':
            var_name = left_side.get('name')
            if var_name in graph.nodes:
                state_node = graph.nodes[var_name]
                if state_node.data and state_node.data.get('type') == 'isa_state':
                    if var_name in self.intermediate_values:
                        for prev_edge in state_node.incoming_edges:
                            if (prev_edge.data.get('type') == 'assignment'
                                    and not prev_edge.data.get('intermediate')):
                                # Only mark as dead if same enable condition
                                prev_enable = prev_edge.data.get('enable')
                                if prev_enable == enable_expr:
                                    prev_edge.data['intermediate'] = True

        edge = Edge(right_node, left_node, data=edge_data)
        graph.add_edge(edge)

        # Track intermediate values for sequential assignments (variable-length instruction support)
        # If this is an assignment to a simple identifier (like pc = ... or ip = ...),
        # record the right-side node as the current value for future reads.
        # Track BOTH unconditional and conditional writes: within a single instruction,
        # subsequent reads need the updated value for computing addresses (e.g., extension
        # word fetches use imem[pc + offset] where pc was conditionally advanced by +2).
        # The condition (e.g., ~exc_taken) only affects the register file update, not
        # the within-instruction dataflow.
        if left_side.get('type') == 'identifier':
            var_name = left_side.get('name')
            # Track for isa_state variables (during parsing, before _rd/_wr split)
            # and for var nodes that already have an intermediate value
            # (e.g., orthogon writes vars that need sequential assignment tracking).
            if var_name in graph.nodes:
                node = graph.nodes[var_name]
                if node.data and node.data.get('type') == 'isa_state':
                    self.intermediate_values[var_name] = right_node
                elif var_name in self.intermediate_values:
                    # Var with existing intermediate — update for sequential tracking
                    self.intermediate_values[var_name] = right_node

    def parse_expression(self) -> Dict:
        return self.parse_ternary()

    def parse_ternary(self) -> Dict:
        expr = self.parse_logical_or()

        if self.match('QUESTION'):
            true_expr = self.parse_logical_or()
            self.consume('COLON', "Expected ':' in ternary operator")
            # Recursively parse ternary to support chained ternary expressions:
            # (a == 1) ? x : (a == 2) ? y : z
            false_expr = self.parse_ternary()
            expr = {
                'type': 'ternary_op',
                'condition': expr,
                'if_true': true_expr,
                'if_false': false_expr
            }

        return expr

    def parse_logical_or(self) -> Dict:
        """Parse logical OR (||) expression"""
        expr = self.parse_logical_and()

        while self.match('LOGICAL_OR'):
            operator = '||'
            right = self.parse_logical_and()
            expr = {
                'type': 'binary_op',
                'operator': operator,
                'left': expr,
                'right': right
            }

        return expr

    def parse_logical_and(self) -> Dict:
        """Parse logical AND (&&) expression"""
        expr = self.parse_bitwise_or()

        while self.match('LOGICAL_AND'):
            operator = '&&'
            right = self.parse_bitwise_or()
            expr = {
                'type': 'binary_op',
                'operator': operator,
                'left': expr,
                'right': right
            }

        return expr

    def parse_equality(self) -> Dict:
        expr = self.parse_comparison()

        while self.match('DOUBLE_EQUALS', 'NOT_EQUALS'):
            operator = self.previous().value
            right = self.parse_comparison()
            expr = {
                'type': 'binary_op',
                'operator': operator,
                'left': expr,
                'right': right
            }

        return expr

    def parse_comparison(self) -> Dict:
        expr = self.parse_shift()

        while self.match('LESS_THAN', 'GREATER_THAN', 'LESS_EQUAL', 'GREATER_EQUAL',
                         'LESS_THAN_SIGNED', 'GREATER_THAN_SIGNED', 'LESS_EQUAL_SIGNED', 'GREATER_EQUAL_SIGNED'):
            operator = self.previous().value
            right = self.parse_shift()
            expr = {
                'type': 'binary_op',
                'operator': operator,
                'left': expr,
                'right': right
            }

        return expr

    def parse_bitwise_or(self) -> Dict:
        """Parse bitwise OR (|) - lower precedence than & but higher than &&"""
        expr = self.parse_bitwise_xor()

        while self.match('PIPE'):
            operator = self.previous().value
            right = self.parse_bitwise_xor()
            expr = {
                'type': 'binary_op',
                'operator': operator,
                'left': expr,
                'right': right
            }

        return expr

    def parse_bitwise_xor(self) -> Dict:
        expr = self.parse_bitwise_and()

        while self.match('CARET'):
            operator = self.previous().value
            right = self.parse_bitwise_and()
            expr = {
                'type': 'binary_op',
                'operator': operator,
                'left': expr,
                'right': right
            }

        return expr

    def parse_bitwise_and(self) -> Dict:
        """Parse bitwise AND (&) - higher precedence than == != (C/Verilog standard)"""
        expr = self.parse_equality()

        while self.match('AMPERSAND'):
            operator = self.previous().value
            right = self.parse_equality()
            expr = {
                'type': 'binary_op',
                'operator': operator,
                'left': expr,
                'right': right
            }

        return expr

    def parse_shift(self) -> Dict:
        expr = self.parse_additive()

        while self.match('LEFT_SHIFT', 'RIGHT_SHIFT', 'ARITH_RIGHT_SHIFT'):
            operator = self.previous().value
            right = self.parse_additive()
            expr = {
                'type': 'binary_op',
                'operator': operator,
                'left': expr,
                'right': right
            }

        return expr

    def parse_additive(self) -> Dict:
        expr = self.parse_multiplicative()

        while self.match('PLUS', 'MINUS'):
            operator = self.previous().value
            right = self.parse_multiplicative()
            expr = {
                'type': 'binary_op',
                'operator': operator,
                'left': expr,
                'right': right
            }

        return expr

    def parse_multiplicative(self) -> Dict:
        expr = self.parse_unary()

        while self.match('MULTIPLY', 'DIVIDE', 'DIVIDE_SIGNED', 'MODULO', 'MODULO_SIGNED'):
            token = self.previous()
            # Map token types to operator strings
            operator_map = {
                'MULTIPLY': '*',
                'DIVIDE': '/',
                'DIVIDE_SIGNED': '/s',
                'MODULO': '%',
                'MODULO_SIGNED': '%s'
            }
            operator = operator_map.get(token.type, token.value)
            right = self.parse_unary()
            expr = {
                'type': 'binary_op',
                'operator': operator,
                'left': expr,
                'right': right
            }

        return expr

    def parse_unary(self) -> Dict:
        # Handle unary operators: ~ (bitwise NOT), - (negation), ! (logical NOT)
        # Also handle reduction operators: | (reduction OR), & (reduction AND), ^ (reduction XOR)
        if self.match('TILDE', 'MINUS', 'LOGICAL_NOT'):
            operator = self.previous().value
            operand = self.parse_unary()  # Right associative
            return {
                'type': 'unary_op',
                'operator': operator,
                'operand': operand
            }
        # Reduction operators: |expr, &expr, ^expr
        if self.match('PIPE', 'AMPERSAND', 'CARET'):
            operator = self.previous().value
            operand = self.parse_unary()  # Right associative
            return {
                'type': 'reduction_op',
                'operator': operator,
                'operand': operand
            }
        return self.parse_primary()

    def parse_primary(self) -> Dict:
        if self.match('NUMBER'):
            return {
                'type': 'literal',
                'value': int(self.previous().value)
            }

        if self.match('HEX_NUMBER'):
            hex_str = self.previous().value
            return {
                'type': 'literal',
                'value': int(hex_str, 16)
            }

        if self.match('VERILOG_HEX_LITERAL'):
            hex_str = self.previous().value
            # Parse format like "32'hFFFF"
            parts = hex_str.split("'h")
            width = int(parts[0])
            hex_digits = parts[1]
            value = int(hex_digits, 16)
            return {
                'type': 'sized_literal',
                'width': width,
                'format': 'hex',
                'original_digits': hex_digits,
                'value': value
            }

        if self.match('BINARY_LITERAL'):
            binary_str = self.previous().value
            # Parse format like "2'b01"
            parts = binary_str.split("'b")
            width = int(parts[0])
            bits = parts[1]
            value = int(bits, 2)
            return {
                'type': 'sized_literal',
                'width': width,
                'format': 'bin',
                'original_digits': bits,
                'value': value
            }

        if self.match('DECIMAL_LITERAL'):
            dec_str = self.previous().value
            # Parse format like "6'd32" or "8'd0"
            parts = dec_str.split("'d")
            width = int(parts[0])
            dec_digits = parts[1]
            value = int(dec_digits, 10)
            return {
                'type': 'sized_literal',
                'width': width,
                'format': 'dec',
                'original_digits': dec_digits,
                'value': value
            }

        if self.match('BINARY_WILDCARD'):
            # Binary wildcard patterns like 0b0** or 0b1**
            # Used in register aliasing: xregs[0b0**] matches xregs[0b000], xregs[0b001], etc.
            wildcard_str = self.previous().value
            # Strip '0b' prefix
            pattern = wildcard_str[2:]
            # Count wildcards to determine width
            width = len(pattern)

            # Extract fixed bits and wildcard positions for later expansion
            fixed_value = 0
            wildcard_positions = []
            for bit_pos, char in enumerate(reversed(pattern)):
                if char == '0':
                    pass  # Fixed 0, value stays 0 for this bit
                elif char == '1':
                    fixed_value |= (1 << bit_pos)
                elif char == '*':
                    wildcard_positions.append(bit_pos)

            return {
                'type': 'binary_wildcard',
                'pattern': pattern,
                'width': width,
                'original': wildcard_str,
                'fixed_value': fixed_value,
                'wildcard_positions': wildcard_positions
            }

        # Handle parenthesized expressions
        if self.match('LPAREN'):
            expr = self.parse_expression()
            self.consume('RPAREN', "Expected ')' after expression")
            return expr

        # Handle Verilog-style concatenation { expr1, expr2, ... }
        # or repetition { count { expr } }
        if self.match('LBRACE'):
            return self.parse_verilog_braces()

        # Handle ctz() and clz() builtins
        if self.match('CTZ') or self.match('CLZ'):
            builtin_name = self.previous().value
            self.consume('LPAREN', f"Expected '(' after {builtin_name}")
            operand = self.parse_expression()
            self.consume('RPAREN', f"Expected ')' after {builtin_name} argument")
            return {
                'type': 'builtin_call',
                'builtin': builtin_name,
                'operand': operand,
            }

        if self.match('IDENTIFIER'):
            name = self.previous().value

            # Check if this is an FP intrinsic function call
            from .fp_intrinsics import is_fp_intrinsic, get_fp_intrinsic, make_fp_operation_node_data
            if is_fp_intrinsic(name) and self.check('LPAREN'):
                self.consume('LPAREN', "Expected '(' after FP intrinsic")
                intrinsic = get_fp_intrinsic(name)
                all_args = []

                # Parse all arguments (operands + optional rounding mode)
                if not self.check('RPAREN'):
                    all_args.append(self.parse_expression())
                    while self.match('COMMA'):
                        all_args.append(self.parse_expression())

                self.consume('RPAREN', "Expected ')' after FP intrinsic arguments")

                # Validate argument count: num_operands + 1 if has_rounding_mode
                expected_count = intrinsic.total_args
                if len(all_args) != expected_count:
                    if intrinsic.has_rounding_mode:
                        raise ValueError(
                            f"FP intrinsic {name} requires {intrinsic.num_operands} operands + "
                            f"rounding mode (total {expected_count} args), got {len(all_args)}. "
                            f"Rounding mode must be passed as the last argument in canonical "
                            f"IEEE 754 encoding (000=RNE, 001=RTZ, 010=RDN, 011=RUP, 100=RMM)."
                        )
                    else:
                        raise ValueError(f"FP intrinsic {name} expects {expected_count} operands, got {len(all_args)}")

                # Separate data operands from rounding mode
                if intrinsic.has_rounding_mode:
                    operands = all_args[:-1]
                    rounding_mode_expr = all_args[-1]
                else:
                    operands = all_args
                    rounding_mode_expr = None

                return {
                    'type': 'fp_intrinsic_call',
                    'intrinsic': name,
                    'operands': operands,
                    'rounding_mode': rounding_mode_expr,
                    'result_type': intrinsic.result_type,
                    'has_rounding_mode': intrinsic.has_rounding_mode,
                    'has_exceptions': intrinsic.has_exceptions,
                    'latency': intrinsic.latency,
                    'pipelined': intrinsic.pipelined,
                }

            # Check if this is a loop variable and substitute its value
            if name in self.loop_vars:
                expr = {
                    'type': 'literal',
                    'value': self.loop_vars[name]
                }
            # Check if this is a register alias and substitute
            elif hasattr(self, 'register_aliases') and name in self.register_aliases:
                alias_value = self.register_aliases[name]
                # Check if this is a wildcard array alias
                if isinstance(alias_value, dict) and alias_value.get('type') == 'wildcard_array':
                    # Keep as identifier for now - will expand after we see the index
                    expr = {
                        'type': 'identifier',
                        'name': name,
                        '_is_wildcard_alias': True  # Mark for later expansion
                    }
                else:
                    # Simple scalar alias - substitute directly
                    expr = alias_value
            else:
                expr = {
                    'type': 'identifier',
                    'name': name
                }

            # Handle array access and bit slicing
            while self.check('LBRACKET'):
                # Look ahead to see if this is a bit slice (contains :) or array access
                saved_pos = self.current
                self.advance()  # consume [

                # Look for colon to determine if this is bit slice
                # Must handle nested brackets: umem[addr_pa[23:0]] is array access, not bit slice
                is_bit_slice = False
                temp_pos = self.current
                bracket_depth = 0  # Track nested bracket depth
                while temp_pos < len(self.tokens):
                    tok_type = self.tokens[temp_pos].type
                    if tok_type == 'LBRACKET':
                        bracket_depth += 1
                    elif tok_type == 'RBRACKET':
                        if bracket_depth == 0:
                            break  # Found our closing bracket
                        bracket_depth -= 1
                    elif tok_type == 'COLON' and bracket_depth == 0:
                        # Only consider colon at depth 0 as bit slice indicator
                        is_bit_slice = True
                        break
                    temp_pos += 1

                # Restore position
                self.current = saved_pos

                if is_bit_slice:
                    bit_range = self.parse_bit_slice()
                    expr = {
                        'type': 'bit_slice',
                        'target': expr,
                        'range': bit_range
                    }
                    break  # Only one bit slice allowed
                else:
                    index = self.parse_array_access()

                    # Check if this is a wildcard alias access (e.g., lregs[i])
                    if expr.get('_is_wildcard_alias'):
                        alias_name = expr.get('name')
                        # Expand the wildcard alias with the actual index
                        expanded_expr = self._expand_wildcard_alias(alias_name, index)
                        if expanded_expr:
                            expr = expanded_expr
                        else:
                            # Fallback if expansion failed
                            expr = {
                                'type': 'array_access',
                                'target': expr,
                                'index': index
                            }
                    else:
                        # Check if expr contains a binary wildcard that should be merged with this index
                        # This handles register aliases like: lregs[idx] where lregs = xregs[0b0**][7:0]
                        # The idx should replace the ** wildcard
                        merged_expr = self._merge_wildcard_index(expr, index)
                        if merged_expr:
                            expr = merged_expr
                        else:
                            expr = {
                                'type': 'array_access',
                                'target': expr,
                                'index': index
                            }

            # Handle CAM associative lookup: name@[key] or name@[key][set_idx]
            # Can also work on indexed CAMs: name[set_idx]@[key]
            if self.check('AT'):
                self.consume('AT', "Expected '@'")
                # Parse the lookup key
                self.consume('LBRACKET', "Expected '[' after '@' for CAM lookup")
                key = self.parse_expression()
                self.consume('RBRACKET', "Expected ']' after CAM lookup key")

                # Check for optional set index: @[key][set_idx]
                set_index = None
                if self.check('LBRACKET'):
                    self.consume('LBRACKET', "Expected '['")
                    set_index = self.parse_expression()
                    self.consume('RBRACKET', "Expected ']'")

                # Get CAM info if available
                cam_info = None
                cam_name = None
                if expr.get('type') == 'identifier':
                    cam_name = expr.get('name')
                    if hasattr(self, 'cam_declarations') and cam_name in self.cam_declarations:
                        cam_info = self.cam_declarations[cam_name]

                expr = {
                    'type': 'cam_lookup',
                    'target': expr,
                    'key': key,
                    'set_index': set_index,
                    'cam_name': cam_name,
                    'cam_info': cam_info,
                }

            return expr

        raise ValueError(f"Unexpected token: {self.peek()}")

    def _merge_wildcard_index(self, expr: Dict, index: Dict) -> Optional[Dict]:
        """
        Merge a binary wildcard in an expression with an actual index.

        For register aliases like: lregs of xregs[0b0**][7:0]
        When accessing lregs[idx], we need to:
        1. Find the binary wildcard 0b0**
        2. Replace it with {1'b0, idx} (concatenation of fixed bits + index)

        Returns the modified expression if a wildcard was merged, None otherwise.
        """
        import copy

        def find_and_replace_wildcard(node, idx):
            """Recursively find binary_wildcard and replace with concatenated index."""
            if not isinstance(node, dict):
                return node, False

            if node.get('type') == 'binary_wildcard':
                # Found the wildcard - create a concatenation expression
                # Pattern like "0**" means: fixed bits = "0", wildcard bits = **
                pattern = node.get('pattern', '')
                width = node.get('width', 2)

                # Count fixed bits (non-* characters) at the start
                fixed_bits = ''
                wildcard_width = 0
                for c in pattern:
                    if c == '*':
                        wildcard_width += 1
                    else:
                        fixed_bits += c

                # Create concatenation: {fixed_bits, index}
                if fixed_bits:
                    fixed_literal = {
                        'type': 'sized_literal',
                        'value': int(fixed_bits, 2),
                        'width': len(fixed_bits),
                        'format': 'bin',
                        'original_digits': fixed_bits
                    }
                    # Return concatenation of fixed bits and index
                    return {
                        'type': 'concatenation',
                        'parts': [fixed_literal, idx]
                    }, True
                else:
                    # No fixed bits, just use the index directly
                    return idx, True

            # For array_access, check the index for wildcards
            if node.get('type') == 'array_access':
                new_index, found = find_and_replace_wildcard(node['index'], idx)
                if found:
                    return {
                        'type': 'array_access',
                        'target': node['target'],
                        'index': new_index
                    }, True

            # For bit_slice, check the target
            if node.get('type') == 'bit_slice':
                new_target, found = find_and_replace_wildcard(node['target'], idx)
                if found:
                    return {
                        'type': 'bit_slice',
                        'target': new_target,
                        'range': node['range']
                    }, True

            return node, False

        new_expr, found = find_and_replace_wildcard(copy.deepcopy(expr), index)
        return new_expr if found else None

    def _expression_has_wildcard(self, expr: Dict) -> bool:
        """Recursively check if an expression contains a wildcard index."""
        if not isinstance(expr, dict):
            return False
        if expr.get('type') == 'binary_wildcard':
            return True
        # Check array_access index
        if expr.get('type') == 'array_access':
            if self._expression_has_wildcard(expr.get('index', {})):
                return True
            # Also check the array base
            if self._expression_has_wildcard(expr.get('target', {})):
                return True
        if expr.get('type') == 'bit_slice':
            # Check the target of the bit slice
            if self._expression_has_wildcard(expr.get('target', {})):
                return True
        # Recursively check other expression types
        for key in ['left', 'right', 'condition', 'if_true', 'if_false', 'operand', 'target']:
            if key in expr and isinstance(expr[key], dict):
                if self._expression_has_wildcard(expr[key]):
                    return True
        return False

    def _deep_copy_expr(self, expr):
        """Deep copy an expression dictionary."""
        import copy
        return copy.deepcopy(expr)

    def _expand_wildcard_alias(self, alias_name: str, index_expr: Dict) -> Dict:
        """
        Expand a wildcard array alias.
        E.g., lregs[i] where lregs is defined as "of xregs[0b0**][7:0]"
        becomes xregs[{0, i}][7:0] where the fixed bits are 0 and wildcard bits come from i.
        """
        alias_info = self.register_aliases.get(alias_name)
        if not alias_info or not isinstance(alias_info, dict) or alias_info.get('type') != 'wildcard_array':
            return None  # Not a wildcard alias

        parent_expr = alias_info['parent_expr']

        # Clone the parent expression
        expanded = self._deep_copy_expr(parent_expr)

        # Find and replace the wildcard index with the actual index expression
        self._substitute_wildcard_in_expr(expanded, index_expr)

        return expanded

    def _substitute_wildcard_in_expr(self, expr: Dict, index_expr: Dict):
        """
        Replace binary_wildcard in expression with actual index.
        Modifies expr in place.
        """
        if expr.get('type') == 'array_access':
            # Handle index that might be a wildcard
            index = expr.get('index', {})
            if index.get('type') == 'binary_wildcard':
                wildcard_info = index
                fixed_value = wildcard_info.get('fixed_value', 0)
                wildcard_positions = wildcard_info.get('wildcard_positions', [])
                # Get the width from the original wildcard pattern (e.g., 0b01*** is 5 bits)
                result_width = wildcard_info.get('width', 5)

                if wildcard_positions:
                    # Use the minimum (rightmost) wildcard position as shift amount
                    # For 0b0**: wildcard_positions=[1,0], min=0, so no shift needed
                    # For 0b**0: wildcard_positions=[2,1], min=1, so shift by 1
                    shift_amount = min(wildcard_positions)
                    # Replace with: (fixed_value | index_expr) or (fixed_value | (index_expr << shift))
                    if shift_amount == 0:
                        expr['index'] = {
                            'type': 'binary_op',
                            'operator': '|',
                            'left': {'type': 'literal', 'value': fixed_value, 'bit_width': result_width},
                            'right': index_expr,
                            'bit_width': result_width  # Ensure result has correct width
                        }
                    else:
                        expr['index'] = {
                            'type': 'binary_op',
                            'operator': '|',
                            'left': {'type': 'literal', 'value': fixed_value, 'bit_width': result_width},
                            'right': {
                                'type': 'binary_op',
                                'operator': '<<',
                                'left': index_expr,
                                'right': {'type': 'literal', 'value': shift_amount},
                                'bit_width': result_width
                            },
                            'bit_width': result_width  # Ensure result has correct width
                        }
                else:
                    expr['index'] = {'type': 'literal', 'value': fixed_value, 'bit_width': result_width}
            else:
                # Recursively substitute in the index
                self._substitute_wildcard_in_expr(index, index_expr)

            # Also check the target (in case it's nested)
            if 'target' in expr and isinstance(expr['target'], dict):
                self._substitute_wildcard_in_expr(expr['target'], index_expr)

        elif expr.get('type') == 'bit_slice':
            # Check the target
            if 'target' in expr and isinstance(expr['target'], dict):
                self._substitute_wildcard_in_expr(expr['target'], index_expr)

    def parse_array_access(self) -> Dict:
        self.consume('LBRACKET', "Expected '['")
        index = self.parse_expression()
        self.consume('RBRACKET', "Expected ']'")
        return index

    def parse_bit_slice(self) -> Tuple:
        """Parse bit slice which can contain expressions when loop variables are involved"""
        self.consume('LBRACKET', "Expected '['")
        high_expr = self.parse_expression()
        self.consume('COLON', "Expected ':'")
        low_expr = self.parse_expression()
        self.consume('RBRACKET', "Expected ']'")

        # Try to evaluate expressions to integers if they're simple
        high = self.evaluate_expression(high_expr) if self.can_evaluate(high_expr) else high_expr
        low = self.evaluate_expression(low_expr) if self.can_evaluate(low_expr) else low_expr

        return (high, low)

    def parse_array_dimension(self) -> Tuple[int, int]:
        self.consume('LBRACKET', "Expected '['")
        high = int(self.consume('NUMBER', "Expected number").value)
        self.consume('COLON', "Expected ':'")
        low = int(self.consume('NUMBER', "Expected number").value)
        self.consume('RBRACKET', "Expected ']'")
        return (high, low)

    def parse_verilog_braces(self) -> Dict:
        """Parse Verilog-style braces - either concatenation or repetition"""
        # LBRACE was already consumed by the caller

        # Look ahead to determine the pattern
        saved_pos = self.current

        # Check if the first element is a repetition pattern (NUMBER followed by {)
        if (self.check('NUMBER') and
            self.current + 1 < len(self.tokens) and
            self.tokens[self.current + 1].type == 'LBRACE'):
            # This could be a repetition, but could also be concatenation with a repetition as first element
            # Let's parse it and see if we hit a comma or closing brace
            count = int(self.advance().value)  # consume NUMBER
            self.consume('LBRACE', "Expected '{'")
            expr = self.parse_expression()
            self.consume('RBRACE', "Expected '}'")

            # Now check what comes next
            if self.check('COMMA'):
                # This is concatenation with a repetition as the first element
                self.current = saved_pos  # restore position
                return self.parse_concatenation_internal()
            elif self.check('RBRACE'):
                # This is a simple repetition
                self.consume('RBRACE', "Expected '}'")
                return {
                    'type': 'repetition',
                    'count': count,
                    'expression': expr
                }
            else:
                raise ValueError(f"Unexpected token after repetition: {self.peek()}")
        else:
            # Regular concatenation
            self.current = saved_pos  # restore position
            return self.parse_concatenation_internal()

    def parse_concatenation_internal(self) -> Dict:
        """Parse Verilog-style concatenation { expr1, expr2, ... }"""
        expressions = []
        expressions.append(self.parse_expression())

        while self.match('COMMA'):
            expressions.append(self.parse_expression())

        self.consume('RBRACE', "Expected '}'")

        return {
            'type': 'concatenation',
            'parts': expressions
        }

    @staticmethod
    def infer_bit_width(operator: str, left_width, right_width, right_expr=None) -> Optional[int]:
        """Infer the result bit width for a binary operation.

        This centralizes the width inference rules so they can be tested
        independently of graph construction.

        Args:
            operator: The binary operator string ('+', '-', '==', '<<', etc.)
            left_width: Bit width of the left operand (or None if unknown).
            right_width: Bit width of the right operand (or None if unknown).
            right_expr: Optional AST dict for the right operand, used for
                        constant-shift analysis.

        Returns:
            The inferred result width, or None if it cannot be determined.
        """
        if left_width is None and right_width is None:
            return None

        # Comparison operators always produce 1-bit result
        if operator in ('==', '!=', '<', '>', '<=', '>=',
                        '<s', '>s', '<=s', '>=s'):
            return 1

        # Shift operators
        if operator in ('<<', '>>', '>>>'):
            if operator == '<<':
                # Left shift: result width = left_width + shift_amount (if constant)
                if right_expr and right_expr.get('type') == 'literal':
                    shift_amount = right_expr.get('value', 0)
                    if left_width is not None:
                        return left_width + int(shift_amount)
                # Variable shift: use left width as minimum
                return left_width
            else:
                # Right shifts preserve or reduce width
                return left_width

        # Arithmetic and bitwise operators use max of operand widths
        if operator in ('+', '-', '&', '|', '^', '*', '/', '/s', '%', '%s'):
            if left_width is not None and right_width is not None:
                max_width = max(left_width, right_width)
                # Addition/subtraction can produce carry/borrow,
                # so widen by 1 to preserve it in intermediates.
                if operator in ('+', '-'):
                    return max_width + 1
                return max_width
            w = left_width if left_width is not None else right_width
            if operator in ('+', '-') and w is not None:
                return w + 1
            return w

        return None

    @staticmethod
    def infer_unary_width(operator: str, operand_width) -> Optional[int]:
        """Infer the result bit width for a unary operation.

        Args:
            operator: The unary operator string ('~', '-', '!').
            operand_width: Bit width of the operand (or None).

        Returns:
            The inferred result width, or None if it cannot be determined.
        """
        if operand_width is None:
            return None
        if operator == '!':
            return 1  # Logical NOT always produces 1-bit
        # Bitwise NOT (~) and negation (-) preserve width
        return operand_width


    def get_or_create_node_for_expression(self, graph: ResourceGraph, expr: Dict, access_mode: str = 'read', enable_expr: Dict = None) -> Node:
        """
        Get or create a node for an expression.

        Args:
            graph: ResourceGraph to add node to
            expr: Expression dictionary
            access_mode: 'read', 'write', or 'read' (default) - used for array access disambiguation
            enable_expr: Optional enable condition expression for writes
        """
        expr_id = self.expression_to_id(expr, access_mode=access_mode)

        if expr_id in graph.nodes:
            return graph.nodes[expr_id]

        # Create new node based on expression type
        if expr['type'] == 'identifier':
            if expr['name'] not in graph.nodes:
                # Create temporary node for undeclared identifier
                node_data = {
                    'type': 'temp_var',
                    'name': expr['name'],
                    'display_name': expr['name']
                }
                node = Node(expr['name'], node_data)
                graph.add_node(node)
            return graph.nodes[expr['name']]

        elif expr['type'] == 'array_access':
            # Check if this is actually a bit-select on a scalar variable
            # If the target is an identifier referring to a scalar var (not a memory),
            # and the index is a literal, convert to bit_slice
            is_bit_select = False
            if expr['index']['type'] == 'literal':
                if expr['target']['type'] == 'identifier':
                    # Check if the identifier is a scalar variable (not a memory)
                    array_id = expr['target']['name']
                    if array_id in graph.nodes:
                        array_node_data = graph.nodes[array_id].data
                        # It's a bit-select if:
                        # 1. It's a 'var' (not 'isa_state'), OR
                        # 2. It's 'isa_state' but not a memory (dimension_count <= 1)
                        is_var = array_node_data.get('type') == 'var'
                        is_scalar_isa_state = (array_node_data.get('type') == 'isa_state' and
                                              not array_node_data.get('is_memory', False))
                        is_bit_select = is_var or is_scalar_isa_state
                elif expr['target']['type'] == 'array_access':
                    # Target is an array_access result (e.g., rf[r1][31]).
                    # The result of rf[r1] is a scalar element, so [31] is a bit-select.
                    is_bit_select = True

            if is_bit_select:
                # Convert to bit_slice with range (index, index)
                index_val = expr['index']['value']
                bit_slice_expr = {
                    'type': 'bit_slice',
                    'target': expr['target'],
                    'range': (index_val, index_val)
                }
                # Recursively call with the bit_slice expression
                return self.get_or_create_node_for_expression(graph, bit_slice_expr, access_mode, enable_expr)

            # It's a genuine array access (like rf[5])
            array_name = self.expression_to_id(expr['target'], 'read')  # Base array name
            index_name = self.expression_to_id(expr['index'], 'read')
            # Display name includes access mode suffix
            suffix = 'wr' if access_mode == 'write' else 'rd'

            # Get the array node first to propagate element width
            array_node = self.get_or_create_node_for_expression(graph, expr['target'], 'read')

            # Propagate element width from the base array
            element_width = array_node.data.get('bit_width')

            node_data = {
                'type': 'array_access',
                'display_name': f"{array_name}[{index_name}]_{suffix}",
                'expression': expr,
                'access_mode': access_mode  # Store access mode in node data
            }
            # Add bit_width if available from the base array
            if element_width is not None:
                node_data['bit_width'] = element_width
            # Add enable expression if this is a write operation
            if enable_expr and access_mode == 'write':
                node_data['enable'] = enable_expr
            node = Node(expr_id, node_data)
            graph.add_node(node)

            # Create edge to the array being accessed
            edge = Edge(array_node, node, data={'type': 'array_base'})
            graph.add_edge(edge)

            # Handle the index - mark it as used_as_index and set indexed_by
            index_node = self.get_or_create_node_for_expression(graph, expr['index'], 'read')
            index_node.used_as_index = True
            index_node.indexed_by = array_node

            # Create edge from index to array access node
            index_edge = Edge(index_node, node, data={'type': 'array_index'})
            graph.add_edge(index_edge)

            # If there's an enable expression, create edge from it to the write node
            if enable_expr and access_mode == 'write':
                enable_node = self.get_or_create_node_for_expression(graph, enable_expr, 'read')
                enable_edge = Edge(enable_node, node, data={'type': 'write_enable'})
                graph.add_edge(enable_edge)

            return node

        elif expr['type'] == 'bit_slice':
            # For reads, use the read target; for writes, use the write target
            target_access_mode = access_mode
            target_name = self.expression_to_id(expr['target'], target_access_mode)
            high, low = expr['range']
            # Calculate bit_width from the slice range
            slice_width = high - low + 1
            node_data = {
                'type': 'bit_slice',
                'display_name': f"{target_name}[{high}:{low}]",
                'expression': expr,
                'access_mode': access_mode,
                'bit_width': slice_width
            }
            node = Node(expr_id, node_data)
            graph.add_node(node)

            # Only create bit_access edge for reads, not writes
            # For writes, the data source will be connected via assignment edge
            if access_mode == 'read':
                target_node = self.get_or_create_node_for_expression(graph, expr['target'], 'read')
                edge = Edge(target_node, node, data={'type': 'bit_access'})
                graph.add_edge(edge)
            else:
                # For writes, we still need to ensure the index expression has nodes created
                # (e.g., for expanded wildcard aliases like xregs[0 | dst_idx][7:0])
                target = expr.get('target', {})
                if target.get('type') == 'array_access':
                    index_expr = target.get('index', {})
                    # Create node for the index expression (it's read to determine write location)
                    self.get_or_create_node_for_expression(graph, index_expr, 'read')

            return node

        elif expr['type'] == 'binary_op':
            left_name = self.expression_to_id(expr['left'], 'read')
            right_name = self.expression_to_id(expr['right'], 'read')

            # Get operand nodes first to access their bit_widths
            left_node = self.get_or_create_node_for_expression(graph, expr['left'], 'read')
            right_node = self.get_or_create_node_for_expression(graph, expr['right'], 'read')

            operator = expr['operator']
            result_width = self.infer_bit_width(
                operator,
                left_node.data.get('bit_width'),
                right_node.data.get('bit_width'),
                right_expr=expr.get('right')
            )

            node_data = {
                'type': 'operation',
                'operator': operator,
                'display_name': f"({left_name} {operator} {right_name})",
                'expression': expr
            }
            if result_width is not None:
                node_data['bit_width'] = result_width

            node = Node(expr_id, node_data)
            graph.add_node(node)

            # Create edges to operands
            edge1 = Edge(left_node, node, data={'type': 'operand', 'position': 'left'})
            edge2 = Edge(right_node, node, data={'type': 'operand', 'position': 'right'})
            graph.add_edge(edge1)
            graph.add_edge(edge2)

            return node

        elif expr['type'] == 'fp_intrinsic_call':
            # FP intrinsic function call (e.g., fp_add(a, b, rm))
            intrinsic_name = expr['intrinsic']
            operands = expr['operands']
            rounding_mode_expr = expr.get('rounding_mode')

            # Get operand nodes
            operand_nodes = []
            operand_names = []
            for op_expr in operands:
                op_node = self.get_or_create_node_for_expression(graph, op_expr, 'read')
                operand_nodes.append(op_node)
                operand_names.append(self.expression_to_id(op_expr, 'read'))

            # Get rounding mode node if present
            rounding_mode_node = None
            if rounding_mode_expr is not None:
                rounding_mode_node = self.get_or_create_node_for_expression(graph, rounding_mode_expr, 'read')

            # Get result type info including packed width from fp_intrinsics
            from .fp_intrinsics import get_intrinsic_result_type
            result_type = expr.get('result_type', 'fp')
            fp_format = 'fp32'  # TODO: infer from operand types
            result_info = get_intrinsic_result_type(intrinsic_name, fp_format)
            result_width = result_info['total_bits']

            node_data = {
                'type': 'fp_operation',
                'fp_intrinsic': intrinsic_name,
                'display_name': f"{intrinsic_name}({', '.join(operand_names)})",
                'expression': expr,
                'bit_width': result_width,
                'value_bits': result_info['value_bits'],
                'flag_bits': result_info.get('flag_bits', 0),
                'has_flags': result_info.get('has_flags', False),
                'value_range': result_info.get('value_range'),
                'flags_range': result_info.get('flags_range'),
                'result_type': result_type,
                'fp_format': fp_format,
                'has_rounding_mode': expr.get('has_rounding_mode', True),
                'has_exceptions': expr.get('has_exceptions', True),
                'latency': expr.get('latency', 3),
                'pipelined': expr.get('pipelined', True),
            }

            node = Node(expr_id, node_data)
            # Set latency on node for timing inference
            node.latency = expr.get('latency', 3) if expr.get('pipelined', True) else 0
            node.variable_latency = not expr.get('pipelined', True)
            graph.add_node(node)

            # Create edges to operands
            position_names = ['first', 'second', 'third']
            for i, op_node in enumerate(operand_nodes):
                pos = position_names[i] if i < len(position_names) else f'operand_{i}'
                edge = Edge(op_node, node, data={'type': 'fp_operand', 'position': pos})
                graph.add_edge(edge)

            # Create edge for rounding mode if present
            if rounding_mode_node is not None:
                rm_edge = Edge(rounding_mode_node, node, data={'type': 'rounding_mode', 'position': 'rounding_mode'})
                graph.add_edge(rm_edge)

            return node

        elif expr['type'] == 'literal':
            node_data = {
                'type': 'literal',
                'value': expr['value'],
                'display_name': str(expr['value'])
            }
            node = Node(expr_id, node_data)
            graph.add_node(node)
            return node

        elif expr['type'] == 'sized_literal':
            fmt = expr.get('format', 'bin')
            width = expr['width']
            value = expr['value']
            original_digits = expr.get('original_digits', str(value))
            fmt_char = {'bin': 'b', 'hex': 'h', 'dec': 'd'}[fmt]
            node_data = {
                'type': 'sized_literal',
                'value': value,
                'width': width,
                'format': fmt,
                'original_digits': original_digits,
                'bit_width': width,
                'display_name': f"{width}'{fmt_char}{original_digits}"
            }
            node = Node(expr_id, node_data)
            graph.add_node(node)
            return node

        elif expr['type'] == 'binary_wildcard':
            node_data = {
                'type': 'binary_wildcard',
                'pattern': expr['pattern'],
                'width': expr['width'],
                'bit_width': expr['width'],  # Set bit_width for concatenation width calculation
                'display_name': expr['original']
            }
            node = Node(expr_id, node_data)
            graph.add_node(node)
            return node

        elif expr['type'] == 'concatenation':
            sub_names = [self.expression_to_id(sub_expr, 'read') for sub_expr in expr['parts']]

            # Get all sub-expression nodes first to calculate total width
            sub_nodes = []
            for sub_expr in expr['parts']:
                sub_node = self.get_or_create_node_for_expression(graph, sub_expr, 'read')
                sub_nodes.append(sub_node)

            # Strip carry-widening from addition/subtraction sub-expressions.
            # In a concatenation like {8'h00, zp_base + X}, the addition should
            # produce its natural width (max of operand widths) without the +1
            # carry bit, since the concatenation defines explicit bit boundaries.
            for sub_node in sub_nodes:
                if (sub_node.data.get('type') == 'operation'
                        and sub_node.data.get('operator') in ('+', '-')):
                    operand_widths = []
                    for edge in sub_node.incoming_edges:
                        if edge.data.get('type') == 'operand':
                            w = edge.source.data.get('bit_width')
                            if w is not None:
                                operand_widths.append(w)
                    if operand_widths:
                        natural_width = max(operand_widths)
                        if sub_node.data.get('bit_width') == natural_width + 1:
                            sub_node.data['bit_width'] = natural_width

            # Calculate concatenation width as sum of all sub-expression widths
            total_width = 0
            all_widths_known = True
            for sub_node in sub_nodes:
                sub_width = sub_node.data.get('bit_width')
                if sub_width is not None:
                    total_width += sub_width
                else:
                    all_widths_known = False

            node_data = {
                'type': 'concatenation',
                'display_name': f"{{{', '.join(sub_names)}}}",
                'expression': expr
            }
            if all_widths_known and total_width > 0:
                node_data['bit_width'] = total_width

            node = Node(expr_id, node_data)
            graph.add_node(node)

            # Create edges to all sub-expressions
            for i, sub_node in enumerate(sub_nodes):
                edge = Edge(sub_node, node, data={'type': 'concatenation_input', 'position': i})
                graph.add_edge(edge)

            return node

        elif expr['type'] == 'repetition':
            sub_name = self.expression_to_id(expr['expression'], 'read')

            # Get sub-expression node first to calculate total width
            sub_node = self.get_or_create_node_for_expression(graph, expr['expression'], 'read')
            sub_width = sub_node.data.get('bit_width')
            count = expr['count']

            node_data = {
                'type': 'repetition',
                'count': count,
                'display_name': f"{{{count}{{{sub_name}}}}}",
                'expression': expr
            }
            # Repetition width is count * sub_expression_width
            if sub_width is not None:
                node_data['bit_width'] = count * sub_width

            node = Node(expr_id, node_data)
            graph.add_node(node)

            # Create edge to the repeated expression
            edge = Edge(sub_node, node, data={'type': 'repetition_input'})
            graph.add_edge(edge)

            return node

        elif expr['type'] == 'ternary_op':
            condition_name = self.expression_to_id(expr['condition'], 'read')
            true_name = self.expression_to_id(expr['if_true'], 'read')
            false_name = self.expression_to_id(expr['if_false'], 'read')

            # Get operand nodes first to access their bit_widths
            condition_node = self.get_or_create_node_for_expression(graph, expr['condition'], 'read')
            true_node = self.get_or_create_node_for_expression(graph, expr['if_true'], 'read')
            false_node = self.get_or_create_node_for_expression(graph, expr['if_false'], 'read')

            # Ternary result width is max of true/false branch widths
            true_width = true_node.data.get('bit_width')
            false_width = false_node.data.get('bit_width')
            result_width = None
            if true_width is not None and false_width is not None:
                result_width = max(true_width, false_width)
            elif true_width is not None:
                result_width = true_width
            elif false_width is not None:
                result_width = false_width

            node_data = {
                'type': 'ternary_op',
                'display_name': f"{condition_name} ? {true_name} : {false_name}",
                'expression': expr
            }
            if result_width is not None:
                node_data['bit_width'] = result_width

            node = Node(expr_id, node_data)
            graph.add_node(node)

            # Create edges to all three operands
            edge1 = Edge(condition_node, node, data={'type': 'ternary_condition'})
            edge2 = Edge(true_node, node, data={'type': 'ternary_true'})
            edge3 = Edge(false_node, node, data={'type': 'ternary_false'})
            graph.add_edge(edge1)
            graph.add_edge(edge2)
            graph.add_edge(edge3)

            return node

        elif expr['type'] == 'unary_op':
            operand_name = self.expression_to_id(expr['operand'], 'read')

            # Get operand node first to access its bit_width
            operand_node = self.get_or_create_node_for_expression(graph, expr['operand'], 'read')
            operator = expr['operator']

            result_width = self.infer_unary_width(
                operator, operand_node.data.get('bit_width')
            )

            node_data = {
                'type': 'operation',
                'operator': operator,
                'display_name': f"({operator}{operand_name})",
                'expression': expr
            }
            if result_width is not None:
                node_data['bit_width'] = result_width

            node = Node(expr_id, node_data)
            graph.add_node(node)

            # Create edge to operand
            edge = Edge(operand_node, node, data={'type': 'operand', 'position': 'unary'})
            graph.add_edge(edge)

            return node

        elif expr['type'] == 'reduction_op':
            # Reduction operators: |, &, ^ - reduce all bits to single bit
            operand_name = self.expression_to_id(expr['operand'], 'read')
            operand_node = self.get_or_create_node_for_expression(graph, expr['operand'], 'read')
            operator = expr['operator']

            # Reduction always produces 1-bit result
            result_width = 1

            node_data = {
                'type': 'operation',
                'operator': f'reduce_{operator}',
                'display_name': f"({operator}{operand_name})",
                'expression': expr,
                'bit_width': result_width
            }

            node = Node(expr_id, node_data)
            graph.add_node(node)

            edge = Edge(operand_node, node, data={'type': 'operand', 'position': 'unary'})
            graph.add_edge(edge)

            return node

        elif expr['type'] == 'cam_lookup':
            # CAM associative lookup: cam@[key] or cam@[key][set_idx]
            # Returns a bitmask of matching entries
            cam_expr = expr.get('target', {})
            key_expr = expr.get('key', {})
            set_index = expr.get('set_index')
            cam_info = expr.get('cam_info', {})

            # Get or create nodes for subexpressions
            cam_node = self.get_or_create_node_for_expression(graph, cam_expr, 'read')
            key_node = self.get_or_create_node_for_expression(graph, key_expr, 'read')

            set_node = None
            if set_index:
                set_node = self.get_or_create_node_for_expression(graph, set_index, 'read')

            # Result width is the number of ways (bitmask)
            num_ways = cam_info.get('num_ways', 1) if cam_info else 1
            result_width = num_ways

            node_data = {
                'type': 'cam_lookup',
                'cam_name': expr.get('cam_name'),
                'cam_info': cam_info,
                'bit_width': result_width,
                'display_name': f"{cam_node.id}@[{key_node.id}]",
                'expression': expr
            }

            node = Node(expr_id, node_data)
            graph.add_node(node)

            # Create edges to CAM and key
            edge = Edge(cam_node, node, data={'type': 'cam_array', 'position': 'cam'})
            graph.add_edge(edge)
            edge = Edge(key_node, node, data={'type': 'cam_key', 'position': 'key'})
            graph.add_edge(edge)

            if set_node:
                edge = Edge(set_node, node, data={'type': 'cam_set_index', 'position': 'set'})
                graph.add_edge(edge)

            return node

        elif expr['type'] == 'builtin_call':
            # Builtin function call: ctz(operand) or clz(operand)
            builtin = expr.get('builtin', 'ctz')
            operand_expr = expr.get('operand', {})

            operand_node = self.get_or_create_node_for_expression(graph, operand_expr, 'read')

            # Get operand width to determine result width
            operand_width = operand_node.data.get('bit_width', 32)
            # ctz/clz result needs enough bits to encode 0..operand_width
            # e.g., for 32-bit input, need 6 bits (0-32)
            import math
            result_width = math.ceil(math.log2(operand_width + 2)) if operand_width > 0 else 1

            node_data = {
                'type': 'builtin_call',
                'builtin': builtin,
                'bit_width': result_width,
                'operand_width': operand_width,
                'display_name': f"{builtin}({operand_node.id})",
                'expression': expr
            }

            node = Node(expr_id, node_data)
            graph.add_node(node)

            # Create edge to operand
            edge = Edge(operand_node, node, data={'type': 'builtin_operand', 'position': 'operand'})
            graph.add_edge(edge)

            return node

        else:
            raise ValueError(f"Unknown expression type: {expr['type']}")

    def expression_to_id(self, expr: Dict, access_mode: str = 'read') -> str:
        """
        Generate a unique ID for an expression.

        Args:
            expr: Expression dictionary
            access_mode: 'read' or 'write' - used to disambiguate array accesses
        """
        if expr['type'] == 'identifier':
            # Check if this identifier is architectural state that needs read/write disambiguation
            identifier_name = expr['name']

            # Check if this is an ISA state identifier by looking for the _rd variant in the graph
            # (Since we now always create _rd/_wr pairs for isa_state declarations)
            if hasattr(self, 'current_graph'):
                # Check if _rd version exists (indicates this is isa_state)
                rd_name = f"{identifier_name}_rd"
                if rd_name in self.current_graph.nodes:
                    # For reads, check if there's an intermediate value from a previous assignment
                    # This enables variable-length instruction support where pc/ip is updated
                    # multiple times within a single instruction
                    if access_mode == 'read' and hasattr(self, 'intermediate_values') and identifier_name in self.intermediate_values:
                        # Use the intermediate node instead of var_rd
                        intermediate_node = self.intermediate_values[identifier_name]
                        return intermediate_node.id

                    # This is an isa_state - use appropriate suffix based on access mode
                    suffix = '_wr' if access_mode == 'write' else '_rd'
                    return f"{identifier_name}{suffix}"

            # Also check if node exists directly in graph (fallback for other node types)
            # This handles isa_state during initial parsing (before _rd/_wr split)
            if hasattr(self, 'current_graph') and identifier_name in self.current_graph.nodes:
                node = self.current_graph.nodes[identifier_name]
                is_isa_state = (node.data.get('type') == 'isa_state' if node.data else False)

                # If it's an ISA state node being read, check for intermediate values first
                # This enables variable-length instruction support during initial parsing
                if is_isa_state and access_mode == 'read':
                    if hasattr(self, 'intermediate_values') and identifier_name in self.intermediate_values:
                        intermediate_node = self.intermediate_values[identifier_name]
                        return intermediate_node.id

                # NOTE: Do NOT add _rd/_wr suffixes here during initial parsing!
                # The arch state splitting happens later in graph processing.
                # Adding suffixes here would change node IDs and break graph merging/pipelining.

            # Final check: for any identifier being read, check intermediate values.
            # This handles orthogon provides outputs (var nodes assigned during
            # inline orthogon expansion) and other non-isa-state intermediates.
            if access_mode == 'read' and hasattr(self, 'intermediate_values') and identifier_name in self.intermediate_values:
                intermediate_node = self.intermediate_values[identifier_name]
                if hasattr(intermediate_node, 'id'):
                    return intermediate_node.id
                # intermediate_values may store a node ID string directly
                if isinstance(intermediate_node, str) and hasattr(self, 'current_graph') and intermediate_node in self.current_graph.nodes:
                    return intermediate_node

            return identifier_name
        elif expr['type'] == 'array_access':
            array_id = self.expression_to_id(expr['target'], access_mode)
            index_id = self.expression_to_id(expr['index'], 'read')  # Index is always read
            # Add _rd or _wr suffix to distinguish read from write array accesses
            suffix = '_wr' if access_mode == 'write' else '_rd'
            return f"{array_id}[{index_id}]{suffix}"
        elif expr['type'] == 'bit_slice':
            target_id = self.expression_to_id(expr['target'], access_mode)
            high, low = expr['range']
            # Add _rd or _wr suffix for bit slices of arch state targets
            # This is needed to disambiguate read vs write when the same bit is both
            # read and written in a single instruction (like xer[34] in subfe/adde)
            suffix = ''
            if hasattr(self, 'current_graph') and expr['target'].get('type') == 'identifier':
                target_name = expr['target'].get('name', '')
                if target_name in self.current_graph.nodes:
                    node = self.current_graph.nodes[target_name]
                    if node.is_arch_state or (node.data and node.data.get('type') == 'isa_state'):
                        suffix = '_wr' if access_mode == 'write' else '_rd'
            return f"{target_id}[{high}:{low}]{suffix}"
        elif expr['type'] == 'binary_op':
            left_id = self.expression_to_id(expr['left'], 'read')  # Operands are always read
            right_id = self.expression_to_id(expr['right'], 'read')
            return f"({left_id} {expr['operator']} {right_id})"
        elif expr['type'] == 'literal':
            return str(expr['value'])
        elif expr['type'] == 'sized_literal':
            fmt = expr.get('format', 'bin')
            fmt_char = {'bin': 'b', 'hex': 'h', 'dec': 'd'}[fmt]
            return f"{expr['width']}'{fmt_char}{expr.get('original_digits', str(expr['value']))}"
        elif expr['type'] == 'binary_wildcard':
            return expr['original']
        elif expr['type'] == 'concatenation':
            sub_ids = [self.expression_to_id(sub_expr, 'read') for sub_expr in expr['parts']]
            return f"{{{', '.join(sub_ids)}}}"
        elif expr['type'] == 'repetition':
            sub_id = self.expression_to_id(expr['expression'], 'read')
            return f"{{{expr['count']}{{{sub_id}}}}}"
        elif expr['type'] == 'ternary_op':
            condition_id = self.expression_to_id(expr['condition'], 'read')
            true_id = self.expression_to_id(expr['if_true'], 'read')
            false_id = self.expression_to_id(expr['if_false'], 'read')
            return f"{condition_id} ? {true_id} : {false_id}"
        elif expr['type'] == 'unary_op':
            operand_id = self.expression_to_id(expr['operand'], 'read')
            return f"{expr['operator']}{operand_id}"
        elif expr['type'] == 'reduction_op':
            operand_id = self.expression_to_id(expr['operand'], 'read')
            return f"{expr['operator']}{operand_id}"
        elif expr['type'] == 'fp_intrinsic_call':
            operand_ids = [self.expression_to_id(op, 'read') for op in expr['operands']]
            return f"{expr['intrinsic']}({', '.join(operand_ids)})"
        elif expr['type'] == 'cam_lookup':
            cam_id = self.expression_to_id(expr.get('target', {}), 'read')
            key_id = self.expression_to_id(expr.get('key', {}), 'read')
            set_index = expr.get('set_index')
            if set_index:
                set_id = self.expression_to_id(set_index, 'read')
                return f"{cam_id}@[{key_id}][{set_id}]"
            else:
                return f"{cam_id}@[{key_id}]"
        elif expr['type'] == 'builtin_call':
            builtin = expr.get('builtin', 'ctz')
            operand_id = self.expression_to_id(expr.get('operand', {}), 'read')
            return f"{builtin}({operand_id})"
        else:
            import sys
            print(f"WARNING: Unhandled expression type '{expr.get('type', 'unknown')}' in expression_to_id: {expr}", file=sys.stderr)
            return f"unknown_{hash(str(expr))}"

    # Helper methods for token parsing
    def match(self, *types) -> bool:
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

        current_token = self.peek()
        raise ValueError(f"{message}. Got {current_token.type} '{current_token.value}' at line {current_token.line}")


def parse_isa_file(filename: str, defines: dict = None) -> ResourceGraph:
    """Parse an ISA file and return a ResourceGraph."""
    parser = ISAParser(defines=defines)
    graph = parser.parse_file(filename)

    # Apply read/write splitting to architectural state nodes
    # This ensures consistency with merged graphs
    from .graph_merger import split_arch_state_nodes
    split_arch_state_nodes(graph)

    # TODO: Re-enable after fixing
    # # Eliminate pass-through variables (e.g., sign_ext_imm = {{...}})
    # # This gives expression nodes meaningful names instead of auto-generated ones
    # # Must be done AFTER arch state splitting to avoid edge reference issues
    # from graph_optimizer import GraphOptimizer
    # optimizer = GraphOptimizer(graph)
    # optimizer.eliminate_passthrough_variables()

    return graph