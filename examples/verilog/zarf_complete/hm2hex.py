#!/usr/bin/env python3
"""
hm2hex.py - Compile H-Machine (.hm) programs to hex files for Verilog simulation.

Takes an .hm source file and produces:
  - imem.hex: Instruction memory image
  - heap.hex: Pre-loaded heap (boxed literal values)
  - cstack.hex: Pre-loaded continuation stack (halt continuation)
  - init.vh: Verilog header with reset values

The converter performs:
  1. Parsing and assembly using the existing hparse/hassembler toolchain
  2. Physical address allocation for builtins and user functions
  3. Boxing of literal argument values as memoized-thunk heap objects
  4. Relocation of itable references to physical addresses
  5. Generation of halt mechanism via cstack pre-load
"""

import sys
import os
import re
import argparse
import types

# Load hparse.py (Python 2) with compatibility fixes for Python 3
HSIM_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'zarf', 'tools', 'python-hsim')
HSIM_DIR = os.path.abspath(HSIM_DIR)

def _load_hparse():
    """Load hparse.py with Python 2->3 compatibility fixes."""
    hparse_path = os.path.join(HSIM_DIR, 'hparse.py')
    with open(hparse_path, 'r') as f:
        source = f.read()
    # Fix Python 2 print statements to print() calls
    source = re.sub(r'^(\s*)print\s+(?![\(])(.*?)$', r'\1print(\2)', source, flags=re.MULTILINE)
    # Compile and execute in a module namespace
    mod = types.ModuleType('hparse')
    mod.__file__ = hparse_path
    code = compile(source, hparse_path, 'exec')
    exec(code, mod.__dict__)
    return mod

_hparse = _load_hparse()
Function = _hparse.Function
Constructor = _hparse.Constructor
Let = _hparse.Let
Case = _hparse.Case
Return = _hparse.Return
LitBranch = _hparse.LitBranch
PatBranch = _hparse.PatBranch
ElseBranch = _hparse.ElseBranch
Name = _hparse.Name
Int = _hparse.Int
Parser = _hparse.Parser
DataWord = _hparse.DataWord
putbits = _hparse.putbits

# Builtin table: name -> (logical_index, arity)
BUILTINS = {
    'error':    (0, 1),
    'add':      (1, 2),
    'sub':      (2, 2),
    'mult':     (3, 2),
    'div':      (4, 2),
    'eq':       (5, 2),
    'leq':      (6, 2),
    'and':      (7, 2),
    'or':       (8, 2),
    'nand':     (9, 2),
    'nor':      (10, 2),
    'xor':      (11, 2),
    'sll':      (12, 2),
    'srl':      (13, 2),
    'sra':      (14, 2),
    'lt':       (15, 2),
    'lequ':     (16, 2),
    'ltu':      (17, 2),
    'neg':      (18, 1),
    'getint':   (0x80, 1),
    'putint':   (0x81, 2),
    'settimer': (0x82, 1),
    'gettimer': (0x83, 1),
    'gccollect': (0x84, 1),
}

# Logical-index-to-name map for builtins actually used
BUILTIN_BY_INDEX = {v[0]: (k, v[1]) for k, v in BUILTINS.items()}


def rename_shadows(p):
    """Rename shadowed let-bindings to avoid the NameMapper's single-namemap bug.

    The hassembler NameMapper builds one flat namemap per function, so if
    a variable name is reused (let x = ... in let x = ... in), the second
    binding overwrites the first and all references resolve to the last one.
    Fix by renaming shadowed bindings to unique names before NameMapper runs.
    """
    for name in p.functions:
        fun = p.functions[name]
        if isinstance(fun, Constructor):
            continue
        defined = set(a.val for a in fun.args)
        defined.update(BUILTINS.keys())
        _rename_shadows_block(fun.instrs, defined, {})


def _rename_shadows_block(instrs, defined, rename_map):
    """Walk instructions, renaming shadowed let-bindings."""
    rename_map = dict(rename_map)  # copy so branches don't leak renames
    for instr in instrs:
        if isinstance(instr, Let):
            # Apply current renames to function ref and args FIRST (before adding new binding)
            if isinstance(instr.f, Name) and instr.f.val in rename_map:
                instr.f = Name(rename_map[instr.f.val])
            for j, arg in enumerate(instr.args):
                if isinstance(arg, Name) and arg.val in rename_map:
                    instr.args[j] = Name(rename_map[arg.val])
            # Check for shadowing
            old_name = instr.name.val
            if old_name in defined:
                counter = 2
                while "{}__{}".format(old_name, counter) in defined:
                    counter += 1
                new_name = "{}__{}".format(old_name, counter)
                instr.name = Name(new_name)
                rename_map[old_name] = new_name
                defined.add(new_name)
            else:
                defined.add(old_name)
        elif isinstance(instr, Case):
            if isinstance(instr.scrut, Name) and instr.scrut.val in rename_map:
                instr.scrut = Name(rename_map[instr.scrut.val])
            for branch in instr.branches:
                _rename_shadows_block(branch.instrs, defined.copy(), rename_map)
        elif isinstance(instr, Return):
            if isinstance(instr.x, Name) and instr.x.val in rename_map:
                instr.x = Name(rename_map[instr.x.val])


def _literal_needs_rewrite(val):
    """Check if a literal value cannot fit in a signed 16-bit field."""
    return val > 32767 or val < -32768


def rewrite_large_literals(p):
    """Rewrite return/case instructions with literals outside signed 16-bit range.

    The return and case opcodes only have 16 bits for the index field,
    which the hardware sign-extends.  Values outside [-32768, 32767]
    can't be encoded directly.  We rewrite
      return <big_int>
    into
      let __biglit_N = __ID__ <big_int> in return __biglit_N

    Similarly for case scrutinees:
      case <big_int> of ...
    becomes
      let __biglit_N = __ID__ <big_int> in case __biglit_N of ...

    The apply (let) instruction encodes arguments in 29-bit words, which
    the boxing pass handles correctly.  This must run before NameChecker
    so that __ID__ gets created if needed.
    """
    counter = [0]
    needs_id = [False]

    def _rewrite_instrs(instrs):
        i = 0
        while i < len(instrs):
            instr = instrs[i]
            if isinstance(instr, Return) and isinstance(instr.x, Int) and _literal_needs_rewrite(instr.x.val):
                tmp_name = "__biglit_{}".format(counter[0])
                counter[0] += 1
                needs_id[0] = True
                let_instr = Let(Name(tmp_name), Name("__ID__"), [instr.x])
                instr.x = Name(tmp_name)
                instrs.insert(i, let_instr)
                i += 2  # skip both the new let and the modified return
            elif isinstance(instr, Case):
                # Rewrite Case scrutinee if it's a large literal
                if isinstance(instr.scrut, Int) and _literal_needs_rewrite(instr.scrut.val):
                    tmp_name = "__biglit_{}".format(counter[0])
                    counter[0] += 1
                    needs_id[0] = True
                    let_instr = Let(Name(tmp_name), Name("__ID__"), [instr.scrut])
                    instr.scrut = Name(tmp_name)
                    instrs.insert(i, let_instr)
                    i += 1  # advance past the new let
                # Recurse into branch bodies
                for branch in instr.branches:
                    _rewrite_instrs(branch.instrs)
                i += 1
            else:
                i += 1

    for name in p.functions:
        fun = p.functions[name]
        if isinstance(fun, Constructor):
            continue
        _rewrite_instrs(fun.instrs)

    if needs_id[0]:
        if "__ID__" not in p.functions:
            p.functions["__ID__"] = Function(Name("__ID__"), [Name("x")], [Return(Name("x"))])
        if "__ID__" not in p.funnames:
            p.funnames.append("__ID__")


class NameChecker:
    """Simplified name checker - walks AST to verify name resolution."""

    def __init__(self, parser):
        self.funnames = parser.funnames
        self.needsID = False
        self.realiased = set()
        self.stalenames = []

        for f in parser.functions.values():
            self.checkfunction(f)

        if self.needsID:
            parser.functions["__ID__"] = Function(Name("__ID__"), [Name("x")], [Return(Name("x"))])
            parser.funnames.append("__ID__")

    def _make_alias(self, name):
        return "__realiased_" + name

    def realias(self, name, instrs, realiased=None):
        if realiased is None:
            realiased = set()
        if name in self.realiased:
            return self._make_alias(name)
        for instr in instrs:
            if isinstance(instr, Case):
                oldset = realiased.copy()
                for branch in instr.branches:
                    realiased = oldset.copy()
                    if isinstance(branch, PatBranch):
                        for field in branch.fields:
                            if field.val == name:
                                if name in realiased:
                                    raise Exception("Name {} already in use".format(name))
                                branch.instrs = [Let(Name(self._make_alias(name)), Name("__ID__"), [Name(name)])] + branch.instrs
                                realiased = realiased.union({name})
                                self.realiased.add(name)
                                self.needsID = True
                    self.realias(name, branch.instrs, realiased)
        if name in self.realiased:
            return self._make_alias(name)

    def checkfunction(self, fun):
        if isinstance(fun, Constructor):
            return
        if not isinstance(fun, Function):
            raise Exception("Bad call")
        args = set(a.val for a in fun.args)
        self.stalenames = []
        self.checkletblock(fun.instrs, args.union(set(BUILTINS.keys())), set(), set())

        self.realiased = set()
        for name, instr in self.stalenames:
            newname = self.realias(name, fun.instrs)
            if isinstance(instr, Let):
                if instr.f.val == name:
                    instr.f = Name(newname)
                for i, arg in enumerate(instr.args):
                    if isinstance(arg, Name) and arg.val == name:
                        instr.args[i] = Name(newname)
            if isinstance(instr, Case):
                if instr.scrut.val == name:
                    instr.scrut = Name(newname)
            if isinstance(instr, Return):
                if isinstance(instr.x, Name) and instr.x.val == name:
                    instr.x = Name(newname)

    def checkletblock(self, instrs, names, fields, stale):
        forwards = set()
        localvs = set().union(names)

        def badarg(arg):
            return arg not in names.union(localvs)

        for instr in instrs:
            if isinstance(instr, Let):
                for arg in instr.args:
                    if isinstance(arg, Name):
                        if arg.val in stale:
                            self.stalenames.append((arg.val, instr))
                        elif badarg(arg.val):
                            forwards.add((arg.val, instr))
                if instr.f.val in stale:
                    self.stalenames.append((instr.f.val, instr))
                elif badarg(instr.f.val) and instr.f.val not in self.funnames:
                    raise Exception("Name {} cannot be resolved".format(instr.f.val))
                localvs.add(instr.name.val)
            if isinstance(instr, (Case, Return)):
                for name, _ in forwards:
                    if badarg(name):
                        raise Exception("Name {} cannot be resolved".format(name))
            if isinstance(instr, Return):
                if isinstance(instr.x, Name):
                    if instr.x.val in stale:
                        self.stalenames.append((instr.x.val, instr))
                    elif badarg(instr.x.val):
                        raise Exception("Name {} cannot be resolved".format(instr.x.val))
            if isinstance(instr, Case):
                self.checkcase(instr, localvs, fields, stale)

    def checkcase(self, instr, names, fields, stale):
        if isinstance(instr.scrut, Name):
            if instr.scrut.val in stale:
                self.stalenames.append((instr.scrut.val, instr))
            elif instr.scrut.val not in names:
                raise Exception("Name {} cannot be resolved".format(instr.scrut.val))
        for branch in instr.branches:
            if isinstance(branch, LitBranch):
                self.checkletblock(branch.instrs, names, set(), stale.union({f.val for f in fields}))
            elif isinstance(branch, PatBranch):
                if branch.cons.val not in self.funnames:
                    raise Exception("Name {} cannot be resolved".format(branch.cons.val))
                self.checkletblock(branch.instrs, names.union({f.val for f in branch.fields}),
                                   branch.fields, stale.union({f.val for f in fields}))
            elif isinstance(branch, ElseBranch):
                self.checkletblock(branch.instrs, names, set(), stale.union({f.val for f in fields}))


class NameMapper:
    """Build name maps for program points."""

    def __init__(self, p):
        funmap = {name: DataWord('itable', idx) for name, (idx, _) in BUILTINS.items()}
        if 'main' not in p.functions:
            raise Exception("Program must define function 'main'")
        funmap['main'] = DataWord('itable', 0x100)
        N = 0x101

        funnames = [name for name in p.funnames if name != 'main']
        for name in funnames:
            funmap[name] = DataWord('itable', N)
            N += 1

        self.function(p.functions['main'], funmap)
        for name in funnames:
            self.function(p.functions[name], funmap)

        self.functions = ['main'] + funnames

    def function(self, fun, funmap):
        if isinstance(fun, Constructor):
            return
        if not isinstance(fun, Function):
            raise Exception("Bad call")
        args = funmap.copy()
        args.update({arg.val: DataWord('arg', i) for i, arg in enumerate(fun.args)})
        self.letblock(fun, fun.instrs, args, 0)

    def letblock(self, head, instrs, oldnames, nlocals):
        names = oldnames.copy()
        nwords = 0
        for instr in instrs:
            if isinstance(instr, Let):
                nwords += 1 + len(instr.args)
                names[instr.name.val] = DataWord('local', nlocals)
                nlocals += 1
            elif isinstance(instr, Case):
                nwords += 1
                if isinstance(instr.scrut, Int):
                    names["__scrutinee__"] = DataWord("literal", instr.scrut.val)
                else:
                    names["__scrutinee__"] = names[instr.scrut.val]
                for branch in instr.branches:
                    if not isinstance(branch, ElseBranch):
                        nwords += 1
                    if isinstance(branch, PatBranch):
                        for i, field in enumerate(branch.fields):
                            names[field.val] = DataWord('casefield', i)
                    nwords += self.letblock(branch, branch.instrs, names, nlocals)
                nlocals += max(branch.nlocals for branch in instr.branches)
            elif isinstance(instr, Return):
                nwords += 1
        head.namemap = names
        head.nwords = nwords
        head.nlocals = nlocals
        return nwords


def assemble_program(source_path, prelude_path=None):
    """Parse and assemble an .hm program, returning binary words and metadata."""
    raw = ""
    if prelude_path:
        with open(prelude_path, 'r') as f:
            raw = f.read() + "\n"
    with open(source_path, 'r') as f:
        raw += f.read()

    p = Parser(raw)
    p.parse()

    rename_shadows(p)
    rewrite_large_literals(p)
    NameChecker(p)
    # De-duplicate funnames — both rewrite_large_literals and NameChecker may add __ID__
    seen = set()
    deduped = []
    for name in p.funnames:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    p.funnames = deduped
    nm = NameMapper(p)

    # Collect all binary words per function (in order)
    func_words = {}
    for name in nm.functions:
        func = p.functions[name]
        words = func.assemble(binary=True)
        func_words[name] = words
        # words[0] = itable word, words[1] = nwords, words[2:] = code

    return p, nm, func_words


def _rebuild_code_with_epilogues(instrs, orig_code, orig_pos):
    """
    Walk AST and original code in lockstep, building new code with:
    1. A 'return caseValue' epilogue after each case expression's branches
    2. Correct n_skip values for case and pattern instructions

    In our single-cycle ISA, the case continuation stays on the stack during branch
    execution. When the branch body returns and pops the case cont, PC goes to
    case_body_return_pc = pc + 1 + n_skip. The epilogue return at that address then
    pops the caller's continuation, completing the case expression properly.

    Args:
        instrs: list of AST instruction nodes
        orig_code: original code words (list of ints)
        orig_pos: mutable [int] tracking position in orig_code
    Returns:
        list of new code words (with epilogues and patched n_skip)
    """
    EPILOGUE_WORD = 0x40050000  # return caseValue (opcode=2, source=5, index=0)
    new_code = []

    for instr in instrs:
        if isinstance(instr, Let):
            n = 1 + len(instr.args)
            new_code.extend(orig_code[orig_pos[0]:orig_pos[0] + n])
            orig_pos[0] += n
        elif isinstance(instr, Return):
            new_code.append(orig_code[orig_pos[0]])
            orig_pos[0] += 1
        elif isinstance(instr, Case):
            # Emit case instruction (will patch n_skip below)
            case_new_idx = len(new_code)
            new_code.append(orig_code[orig_pos[0]])
            orig_pos[0] += 1

            total_branch_new_words = 0

            for branch in instr.branches:
                if not isinstance(branch, ElseBranch):
                    # Emit pattern instruction (will patch n_skip below)
                    pattern_new_idx = len(new_code)
                    new_code.append(orig_code[orig_pos[0]])
                    orig_pos[0] += 1
                    total_branch_new_words += 1

                # Process branch body recursively
                body_start = len(new_code)
                body_words = _rebuild_code_with_epilogues(branch.instrs, orig_code, orig_pos)
                new_code.extend(body_words)
                body_new_len = len(new_code) - body_start
                total_branch_new_words += body_new_len

                # Patch pattern n_skip with actual body length (includes nested epilogues)
                if not isinstance(branch, ElseBranch):
                    word = new_code[pattern_new_idx]
                    word = (word & ~(0x3FF << 19)) | ((body_new_len & 0x3FF) << 19)
                    new_code[pattern_new_idx] = word

            # Insert epilogue: return caseValue
            new_code.append(EPILOGUE_WORD)

            # Patch case n_skip = total branch words (epilogue is at pc + 1 + n_skip)
            word = new_code[case_new_idx]
            word = (word & ~(0x3FF << 19)) | ((total_branch_new_words & 0x3FF) << 19)
            new_code[case_new_idx] = word

    return new_code


def add_case_epilogues(p, nm, func_words):
    """
    Rebuild each function's code with case epilogues and correct n_skip values.
    Updates func_words in place with new code and adjusted nwords.
    """
    for name in nm.functions:
        func = p.functions[name]
        if isinstance(func, Constructor):
            continue

        words = func_words[name]
        itable = words[0]
        orig_nwords = words[1]
        orig_code = words[2:]

        assert len(orig_code) == orig_nwords, \
            "Code length mismatch for {}: {} != {}".format(name, len(orig_code), orig_nwords)

        orig_pos = [0]
        new_code = _rebuild_code_with_epilogues(func.instrs, orig_code, orig_pos)

        assert orig_pos[0] == len(orig_code), \
            "Did not consume all original code for {}: consumed {} of {}".format(
                name, orig_pos[0], len(orig_code))

        new_nwords = len(new_code)
        func_words[name] = [itable, new_nwords] + new_code

    # Replace __ID__ with a forcing version.
    # The default __ID__ compiles to 'return arg[0]', which returns the raw argument.
    # When used for realiasing casefields, this creates an extra thunk indirection:
    # the __ID__ thunk returns the casefield's value (which may itself be an unevaluated
    # thunk), and the caller's case instruction sees a non-WHNF value at pattern matching.
    #
    # The fix: compile __ID__ as 'case arg[0] of { _ => return caseValue }', which
    # forces the argument to WHNF before returning. This matches the reference hardware's
    # name-table-based approach where realiasing is a zero-cost indirection.
    #
    # Binary: [CASE n_skip=1 src=arg idx=0] [RETURN caseValue] [RETURN caseValue (epilogue)]
    if "__ID__" in func_words:
        itable = func_words["__ID__"][0]
        CASE_ARG0_NSKIP1 = 0x60080000  # opcode=011, n_skip=1, source=000(arg), index=0
        RET_CASEVAL = 0x40050000        # opcode=010, source=101(caseValue), index=0
        func_words["__ID__"] = [itable, 3, CASE_ARG0_NSKIP1, RET_CASEVAL, RET_CASEVAL]


def build_relocation_map(nm, func_words):
    """
    Build a map from logical itable index to physical imem address.

    Layout:
      - Builtins occupy 3 words each: [info_table, builtin_instruction, trampoline_return]
      - User functions occupy (1 + nwords) each: [info_table, code...]

    The nwords field from the assembler is metadata only and is NOT stored in imem.
    Code starts immediately after the info table at func_addr + 1.
    The trampoline_return is a 'return caseValue' instruction (0x40050000) used
    after thunk evaluation to pop the eval continuation and re-enter the builtin.
    """
    reloc = {}  # logical_index -> physical_address
    addr = 0

    # Collect which builtins are actually referenced
    # We need to allocate space for ALL builtins that might be referenced
    # Builtins are at logical indices defined in BUILTINS
    # Allocate them in order of logical index
    builtin_indices = sorted(BUILTIN_BY_INDEX.keys())

    for idx in builtin_indices:
        reloc[idx] = addr
        addr += 3  # info table + builtin instruction + trampoline return

    # User functions: main is at 0x100, others at 0x101, 0x102, ...
    for name in nm.functions:
        func = func_words[name]
        # Determine logical index
        if name == 'main':
            logical_idx = 0x100
        else:
            # Find it from the function's own namemap
            dw = func_words[name]  # This is the assembled words
            # We need the logical index from NameMapper
            # Main is 0x100, others are 0x101+
            idx_in_list = nm.functions.index(name)
            if idx_in_list == 0:
                logical_idx = 0x100
            else:
                logical_idx = 0x100 + idx_in_list

        nwords = func[1]  # nwords field from assembler
        reloc[logical_idx] = addr
        addr += 1 + nwords  # info table + code words (nwords is NOT stored in imem)

    return reloc, addr  # addr is now total imem size


def collect_literals(func_words):
    """
    Scan all code words for literal arguments (source=4) and collect unique values.
    Returns a set of literal integer values that need boxing.
    """
    literals = set()

    for name, words in func_words.items():
        # words[0] = itable, words[1] = nwords, words[2:] = code
        code = words[2:]
        i = 0
        while i < len(code):
            word = code[i]
            opcode = (word >> 29) & 0x7

            if opcode == 1:  # apply
                n_args = (word >> 19) & 0x3FF
                # Check function source
                src = (word >> 16) & 0x7
                # Check each argument word
                for j in range(n_args):
                    if i + 1 + j < len(code):
                        arg_word = code[i + 1 + j]
                        arg_src = (arg_word >> 29) & 0x7
                        arg_idx = arg_word & 0x1FFFFFFF
                        if arg_src == 4:  # literal (sign-extended 29-bit value)
                            # Sign-extend from 29 bits to match hardware decode
                            if arg_idx & (1 << 28):
                                arg_idx |= ~0x1FFFFFFF
                                arg_idx &= 0xFFFFFFFF  # keep as 32-bit unsigned Python int
                            literals.add(arg_idx)
                i += 1 + (n_args if opcode == 1 else 0)
                continue

            if opcode == 2:  # return
                src = (word >> 16) & 0x7
                idx = word & 0xFFFF
                if src == 4:  # literal return (sign-extended 16-bit value)
                    if idx & (1 << 15):
                        idx |= 0xFFFF0000  # sign-extend to 32 bits
                    literals.add(idx)

            if opcode == 3:  # case
                src = (word >> 16) & 0x7
                idx = word & 0xFFFF
                if src == 4:  # literal scrutinee (sign-extended 16-bit value)
                    if idx & (1 << 15):
                        idx |= 0xFFFF0000  # sign-extend to 32 bits
                    literals.add(idx)

            i += 1

    return literals


def box_literals(literals, heap_base):
    """
    Create boxed (memoized thunk) heap objects for each literal value.

    Each boxed literal occupies 2 heap words:
      [0]: header = {2'b11, 1'b1, 13'b0, value[15:0]}  -- memoized, eval_tag=1 (primitive)
      [1]: value (full 32-bit)

    Returns:
      - boxed_map: literal_value -> heap_address
      - heap_words: list of (addr, value) pairs
      - next_free: next free heap address
    """
    boxed_map = {}
    heap_words = []
    addr = heap_base

    for lit_val in sorted(literals):
        # Header: [31:30]=11 (memoized), [29]=1 (eval_tag=primitive), [28:0]=don't care
        # We store the value in bits [28:0] of header too for convenience, but
        # the actual value is read from addr+1
        val_32 = lit_val & 0xFFFFFFFF
        header = (0b11 << 30) | (1 << 29) | (val_32 & 0x1FFF_FFFF)
        heap_words.append((addr, header))
        heap_words.append((addr + 1, val_32))
        boxed_map[lit_val] = addr
        addr += 2

    return boxed_map, heap_words, addr


def patch_code_words(func_words, reloc, boxed_map):
    """
    Patch all code words with relocated addresses and boxed literals.

    For each code word:
      - Instruction words with source=7 (itable): relocate the 16-bit index
      - Argument words with source=4 (literal): replace with source=7 pointing to boxed heap addr
      - Argument words with source=7 (itable): relocate the 29-bit index
    """
    patched = {}

    for name, words in func_words.items():
        itable = words[0]
        nwords_field = words[1]
        code = list(words[2:])

        i = 0
        while i < len(code):
            word = code[i]
            opcode = (word >> 29) & 0x7

            if opcode == 1:  # apply
                n_args = (word >> 19) & 0x3FF
                src = (word >> 16) & 0x7
                idx = word & 0xFFFF

                # Relocate function reference if itable
                if src == 7:
                    if idx in reloc:
                        code[i] = (code[i] & ~0xFFFF) | (reloc[idx] & 0xFFFF)

                # Patch argument words
                for j in range(n_args):
                    if i + 1 + j < len(code):
                        arg_word = code[i + 1 + j]
                        arg_src = (arg_word >> 29) & 0x7
                        arg_idx = arg_word & 0x1FFFFFFF

                        if arg_src == 4:  # literal -> boxed heap reference
                            # Sign-extend from 29 bits to match collect_literals
                            lit_val = arg_idx
                            if lit_val & (1 << 28):
                                lit_val |= ~0x1FFFFFFF
                                lit_val &= 0xFFFFFFFF
                            if lit_val in boxed_map:
                                heap_addr = boxed_map[lit_val]
                                # Change to source=7 (itable) pointing to heap addr
                                # But actually source=7 in argument words means "itable index"
                                # which will be the raw value. In hardware, source=7 arg_val = index_ext.
                                # So we store the heap address as the index.
                                code[i + 1 + j] = (7 << 29) | (heap_addr & 0x1FFFFFFF)
                        elif arg_src == 7:  # itable reference in argument
                            if arg_idx in reloc:
                                code[i + 1 + j] = (7 << 29) | (reloc[arg_idx] & 0x1FFFFFFF)

                i += 1 + n_args
                continue

            elif opcode == 2:  # return
                src = (word >> 16) & 0x7
                idx = word & 0xFFFF
                if src == 7:  # itable
                    if idx in reloc:
                        code[i] = (code[i] & ~0xFFFF) | (reloc[idx] & 0xFFFF)

            elif opcode == 3:  # case
                src = (word >> 16) & 0x7
                idx = word & 0xFFFF
                if src == 7:  # itable
                    if idx in reloc:
                        code[i] = (code[i] & ~0xFFFF) | (reloc[idx] & 0xFFFF)

            elif opcode == 5:  # pattern_cons
                # The tag field is the constructor's itable index
                idx = word & 0xFFFF
                if idx in reloc:
                    code[i] = (code[i] & ~0xFFFF) | (reloc[idx] & 0xFFFF)

            i += 1

        patched[name] = (itable, nwords_field, code)

    return patched


def build_imem(patched, reloc, nm):
    """
    Build the full instruction memory image.

    Layout:
      1. Builtin entries (3 words each): info_table + builtin_instruction + trampoline_return
      2. User function entries: info_table + code_words
    """
    # Find total size needed
    max_addr = 0
    for idx, addr in reloc.items():
        if idx < 0x100:  # builtin
            max_addr = max(max_addr, addr + 3)
        else:
            name_idx = idx - 0x100
            if name_idx < len(nm.functions):
                name = nm.functions[name_idx]
                _, nwords, code = patched[name]
                max_addr = max(max_addr, addr + 1 + nwords)

    imem = [0] * max_addr

    # Fill builtin entries
    builtin_indices = sorted(BUILTIN_BY_INDEX.keys())
    for idx in builtin_indices:
        name, arity = BUILTIN_BY_INDEX[idx]
        addr = reloc[idx]

        # Info table: [31]=0 (function, not constructor), [30:18]=arity, [17:8]=nfree=0, [7:0]=nlocals=0
        # Actually for builtins treated as constructors? No - builtins are functions.
        # Use same format as Function.assemble: {0, arity[10:0], 0[9:0], 0[9:0]}
        # But note: itable format is [31]=is_cons, [30:20]=arity, [19:10]=nfree, [9:0]=nlocals
        # From hparse.py: putbits(0, 31, 31) | putbits(arity, 20, 30) | putbits(0, 10, 19) | putbits(nlocals, 0, 9)
        itable_word = putbits(0, 31, 31) | putbits(arity, 20, 30) | putbits(0, 10, 19) | putbits(0, 0, 9)
        imem[addr] = itable_word

        # Builtin instruction: opcode=110, unused, source=000, builtin_index
        builtin_instr = putbits(0x6, 29, 31) | putbits(0, 19, 28) | putbits(0, 16, 18) | putbits(idx, 0, 15)
        imem[addr + 1] = builtin_instr

        # Trampoline return: return caseValue (opcode=010, source=101, index=0)
        # After thunk evaluation, this pops the eval continuation to re-enter the builtin
        trampoline_return = 0x40050000
        imem[addr + 2] = trampoline_return

    # Fill user function entries
    for name in nm.functions:
        name_idx = nm.functions.index(name)
        logical_idx = 0x100 + name_idx
        addr = reloc[logical_idx]
        itable, nwords, code = patched[name]

        imem[addr] = itable
        for j, w in enumerate(code):
            imem[addr + 1 + j] = w

    return imem


def build_halt_continuation(reloc, imem_size, halt_args_addr, boxed_zero_addr):
    """
    Build a halt mechanism: a case continuation at cstack[0..4] that forces
    evaluation of main's return value, then halts via builtin error.

    The halt sequence in imem:
      halt_case:   case instruction (source=3 caseValue, n_skip=1)
      halt_return: return caseValue (source=3)
      halt_error:  builtin error 0

    When main returns, cont_pop pops the case continuation and jumps to
    halt_case. The case instruction forces evaluation of the return value
    (entering thunks if needed), then the wildcard body returns the value,
    popping the inner case cont which jumps to halt_error for clean halt.

    Args:
      reloc: relocation map
      imem_size: current imem size (halt instructions appended here)
      halt_args_addr: heap address of the pre-allocated halt argument frame
                      (heap[halt_args_addr] = boxed_zero_addr)
      boxed_zero_addr: heap address of the boxed literal 0

    Returns:
      - cstack_words: list of 5 words for cstack[0..4]
      - halt_imem_addr: address of the halt case instruction in imem
      - extra_imem: list of (addr, word) pairs to append to imem
    """
    halt_addr = imem_size

    # case instruction: opcode=011, n_skip=1, source=101 (caseValue/eval_reg), index=0
    # This forces evaluation of eval_reg (main's return value)
    halt_case = putbits(0x3, 29, 31) | putbits(1, 19, 28) | putbits(5, 16, 18) | putbits(0, 0, 15)

    # return caseValue: opcode=010, source=101 (caseValue/eval_reg), index=0
    # The "wildcard body" — just returns the forced value
    halt_return = putbits(0x2, 29, 31) | putbits(0, 19, 28) | putbits(5, 16, 18) | putbits(0, 0, 15)

    # builtin error: opcode=110, builtin_index=0 (error)
    halt_error = putbits(0x6, 29, 31) | putbits(0, 19, 28) | putbits(0, 16, 18) | putbits(0, 0, 15)

    extra_imem = [
        (halt_addr, halt_case),
        (halt_addr + 1, halt_return),
        (halt_addr + 2, halt_error),
    ]

    # Case continuation: type=00, saved_pc = halt_case (the case instruction)
    # When main returns, cont_pop jumps to the case instruction which forces eval
    cstack_word0 = (0b00 << 30) | (halt_addr & 0x3FFFFFFF)  # case cont, pc=halt_case
    cstack_word1 = 0  # env_clo (don't care)
    cstack_word2 = halt_args_addr  # env_args -> halt argument frame
    cstack_word3 = 0  # lsp
    cstack_word4 = 0  # lb

    cstack_words = [cstack_word0, cstack_word1, cstack_word2, cstack_word3, cstack_word4]

    return cstack_words, halt_addr, extra_imem


def write_hex(filepath, words, word_width=32):
    """Write a hex memory file for $readmemh."""
    with open(filepath, 'w') as f:
        for i, word in enumerate(words):
            word = word & ((1 << word_width) - 1)
            f.write('{:08x}\n'.format(word))


def write_hex_sparse(filepath, entries, default=0, total_size=None):
    """Write a hex file with address annotations for sparse data."""
    with open(filepath, 'w') as f:
        for addr, word in entries:
            word = word & 0xFFFFFFFF
            f.write('@{:05x} {:08x}\n'.format(addr, word))


def write_init_vh(filepath, params):
    """Write a Verilog header file with reset parameter values."""
    with open(filepath, 'w') as f:
        f.write("// Auto-generated initialization parameters\n")
        f.write("// Generated by hm2hex.py\n\n")
        for name, value in sorted(params.items()):
            if isinstance(value, int):
                f.write("localparam [31:0] INIT_{} = 32'h{:08x};\n".format(name.upper(), value & 0xFFFFFFFF))
            else:
                f.write("localparam INIT_{} = {};\n".format(name.upper(), value))


def main():
    parser = argparse.ArgumentParser(
        description='Compile H-Machine programs to hex files for Verilog simulation'
    )
    parser.add_argument('prog', metavar='program.hm',
                        help='H-Machine source program')
    parser.add_argument('-o', '--output-dir', default='.',
                        help='Output directory (default: current directory)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    parser.add_argument('-p', '--prelude', metavar='Prelude.hm',
                        help='Prelude file to prepend (library functions)')
    args = parser.parse_args()

    if not os.path.isfile(args.prog):
        print("Error: Source program '{}' does not exist".format(args.prog), file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    print("=== hm2hex: Compiling {} ===".format(args.prog))

    # Step 1: Parse and assemble (with optional prelude)
    print("  Parsing and assembling...")
    if args.prelude:
        if not os.path.isfile(args.prelude):
            print("Error: Prelude file '{}' does not exist".format(args.prelude), file=sys.stderr)
            sys.exit(1)
        print("  Including prelude: {}".format(args.prelude))
        p, nm, func_words = assemble_program(args.prog, prelude_path=args.prelude)
    else:
        p, nm, func_words = assemble_program(args.prog)

    # Step 1b: Add case epilogues and patch n_skip fields
    # Our single-cycle ISA needs a 'return caseValue' epilogue after each case
    # expression's branches. Also patches n_skip values for case and pattern instructions.
    print("  Adding case epilogues and patching n_skip...")
    add_case_epilogues(p, nm, func_words)

    if args.verbose:
        print("  Functions: {}".format(nm.functions))
        for name in nm.functions:
            words = func_words[name]
            print("    {}: itable=0x{:08x} nwords={} code={}".format(
                name, words[0], words[1], len(words) - 2))

    # Step 2: Build relocation map
    print("  Building relocation map...")
    reloc, imem_size = build_relocation_map(nm, func_words)

    if args.verbose:
        print("  Relocation map:")
        for idx in sorted(reloc.keys()):
            if idx < 0x100:
                name = BUILTIN_BY_INDEX.get(idx, ("?", 0))[0]
                print("    builtin {:3d} ({:8s}) -> imem[{:5d}]".format(idx, name, reloc[idx]))
            else:
                fn_idx = idx - 0x100
                name = nm.functions[fn_idx] if fn_idx < len(nm.functions) else "?"
                print("    func   0x{:03x} ({:8s}) -> imem[{:5d}]".format(idx, name, reloc[idx]))

    # Step 3: Collect and box literals
    print("  Boxing literal values...")
    literals = collect_literals(func_words)
    literals.add(0)  # Always box 0 — needed by halt mechanism (error code 0 = success)
    heap_base = 0  # boxed literals start at heap[0]
    boxed_map, heap_words, next_free_heap = box_literals(literals, heap_base)

    if args.verbose:
        print("  Boxed literals ({} unique):".format(len(boxed_map)))
        for val, addr in sorted(boxed_map.items()):
            print("    value {:6d} -> heap[{:5d}]".format(val, addr))

    # Step 4: Patch code words
    print("  Patching code with relocations...")
    patched = patch_code_words(func_words, reloc, boxed_map)

    # Step 5: Build imem image
    print("  Building instruction memory image...")
    imem = build_imem(patched, reloc, nm)

    # Step 6: Build halt continuation
    # Allocate a halt argument frame in the heap: heap[next_free_heap] = boxed_zero_addr
    # The error builtin reads arg1_ref = heap[env_args], so env_args must point here
    print("  Building halt mechanism...")
    halt_args_addr = next_free_heap
    boxed_zero_addr = boxed_map.get(0, 0)  # address of boxed literal 0
    heap_words.append((halt_args_addr, boxed_zero_addr))
    next_free_heap += 1
    cstack_words, halt_addr, extra_imem = build_halt_continuation(reloc, len(imem),
                                                                    halt_args_addr, boxed_zero_addr)

    # Extend imem with halt entries
    for addr, word in extra_imem:
        while len(imem) <= addr:
            imem.append(0)
        imem[addr] = word

    # Step 7: Write output files
    print("  Writing output files...")

    # imem.hex
    imem_path = os.path.join(output_dir, 'imem.hex')
    write_hex(imem_path, imem)
    print("    imem.hex: {} words".format(len(imem)))

    # heap.hex - sparse format for pre-loaded boxed literals
    heap_path = os.path.join(output_dir, 'heap.hex')
    write_hex_sparse(heap_path, heap_words)
    print("    heap.hex: {} words".format(len(heap_words)))

    # cstack.hex
    cstack_path = os.path.join(output_dir, 'cstack.hex')
    write_hex(cstack_path, cstack_words)
    print("    cstack.hex: {} words".format(len(cstack_words)))

    # init.vh - reset values
    # main's first code word is at reloc[0x100] + 1 (skip info table)
    main_code_addr = reloc[0x100] + 1
    init_params = {
        'pc_rd': main_code_addr,
        'fp': next_free_heap,
        'csp_rd': 5,  # after pre-loaded halt continuation (5 words)
        'lsp_rd': 0,
        'lb_rd': 0,
        'env_args': 0,
        'env_clo': 0,
        'eval_reg_rd': 0,
        'eval_tag_rd': 0,
        'ct_rd': 0,
        'halted_rd': 0,
        'error_code_rd': 0,
        'io_out_valid_rd': 0,
    }

    init_path = os.path.join(output_dir, 'init.vh')
    write_init_vh(init_path, init_params)
    print("    init.vh: {} parameters".format(len(init_params)))

    # Summary
    print("\n=== Summary ===")
    print("  Program: {}".format(args.prog))
    print("  Functions: {} user + {} builtins".format(
        len(nm.functions), len(BUILTIN_BY_INDEX)))
    print("  imem: {} words".format(len(imem)))
    print("  heap pre-loaded: {} words ({} boxed literals)".format(
        len(heap_words), len(boxed_map)))
    print("  Reset PC: {} (0x{:08x})".format(main_code_addr, main_code_addr))
    print("  Reset FP: {} (first free heap)".format(next_free_heap))
    print("  Halt continuation at cstack[0..4]")
    print("")

    if args.verbose:
        # Dump first few imem words for debugging
        print("  imem contents:")
        for i, w in enumerate(imem[:min(40, len(imem))]):
            opcode = (w >> 29) & 0x7
            opcodes = {0: '---', 1: 'APP', 2: 'RET', 3: 'CAS', 4: 'PLT', 5: 'PCN', 6: 'BLT'}
            opc_str = opcodes.get(opcode, '???')
            marker = ""
            for idx, addr in reloc.items():
                if addr == i:
                    if idx < 0x100:
                        marker = " <-- builtin {} ({})".format(idx, BUILTIN_BY_INDEX.get(idx, ("?",))[0])
                    else:
                        fn_idx = idx - 0x100
                        n = nm.functions[fn_idx] if fn_idx < len(nm.functions) else "?"
                        marker = " <-- func {} ({})".format(idx, n)
            print("    [{:5d}] {:08x}  {}{}".format(i, w & 0xFFFFFFFF, opc_str, marker))


if __name__ == '__main__':
    main()
