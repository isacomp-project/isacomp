#!/usr/bin/env python3
"""
Create a 3-layer hierarchical AES JSON:
1. Parent: AES ILA (WRITE_ADDRESS, START_ENCRYPT, etc.)
2. Child: AES_BLOCK (LOAD, OPERATE, STORE)
3. Grandchild: aes128 function (FirstRound, IntermediateRound, FinalRound)

The AES_BLOCK child should be embedded in the parent's 'c' array,
and the aes128 grandchild should be embedded in AES_BLOCK's 'c' array.
"""

import json


def main():
    print("Creating 3-layer hierarchical AES JSON...")

    # Load parent (AES ILA)
    with open('test_data/aes_full.json') as f:
        parent = json.load(f)
    print(f"  Loaded parent: {len(parent['a'])} expressions, {len(parent['t']['instr'])} instructions")

    # Load AES_BLOCK child
    with open('test_data/aes_block_child.json') as f:
        aes_block = json.load(f)
    print(f"  Loaded AES_BLOCK: {len(aes_block['a'])} expressions, {len(aes_block['t']['instr'])} instructions")

    # Load aes128 grandchild
    with open('test_data/aes128_function.json') as f:
        aes128 = json.load(f)
    print(f"  Loaded aes128: {len(aes128['a'])} expressions, {len(aes128['t']['instr'])} instructions")

    # Embed aes128 as a child of AES_BLOCK
    # Children in 'c' array should be the 't' structure directly
    aes128_t = aes128['t'].copy()
    aes128_t['n'] = 'aes128'  # Set name to match function reference

    aes_block_t_with_child = aes_block['t'].copy()
    aes_block_t_with_child['c'] = [aes128_t]

    # Embed AES_BLOCK (with aes128 grandchild) as a child of parent
    # Children go inside the parent's 't' structure, as the 't' dict directly
    parent_t_with_child = parent['t'].copy()
    parent_t_with_child['c'] = [aes_block_t_with_child]

    # NOTE: We lose the 'a' arrays from children when using this format
    # The parser expects children to share the parent's expression array
    # So we need to merge all expressions into the parent's 'a' array

    # Calculate maximum expression IDs to avoid collisions when offsetting
    def get_max_expr_id(expr_array):
        """Get the maximum expression ID in an array."""
        max_id = 0
        for expr in expr_array:
            expr_id = expr.get('i', 0)
            if expr_id > max_id:
                max_id = expr_id
        return max_id

    parent_max_id = get_max_expr_id(parent['a'])
    print(f"  Parent max expression ID: {parent_max_id}")

    # Use max ID + 1 as offset for child expressions
    parent_expr_offset = parent_max_id + 1

    # Store array lengths for reference
    parent_expr_count = len(parent['a'])
    aes_block_expr_count = len(aes_block['a'])
    aes128_expr_count = len(aes128['a'])

    # Build mapping tables for input states (must be done before combining arrays)
    def build_state_mapping(parent_json, child_json):
        """Build mapping from child input state IDs to parent state IDs."""
        mapping = {}

        # Get parent state declarations
        parent_states = {}
        for i, expr in enumerate(parent_json['a']):
            if expr.get('u') == 1 and 'n' in expr:
                parent_states[expr['n']] = expr['i']

        # Get child input state declarations
        child_inputs = child_json['t'].get('i', [])
        for expr_id in child_inputs:
            # Find the expression in child's array
            for expr in child_json['a']:
                if expr.get('i') == expr_id and expr.get('u') == 1 and 'n' in expr:
                    state_name = expr['n']
                    if state_name in parent_states:
                        # Map child input state ID to parent state ID
                        mapping[expr_id] = parent_states[state_name]
                    break

        return mapping

    # Build mappings
    aes_block_mapping = build_state_mapping(parent, aes_block)
    print(f"  AES_BLOCK input state mapping: {aes_block_mapping}")

    aes128_mapping = build_state_mapping(aes_block, aes128)
    print(f"  aes128 input state mapping: {aes128_mapping}")

    # Reindex expression arrays
    def reindex_expr_array(expr_array, offset, mapping=None):
        """Reindex expressions in an array, updating 'i' and 'a' fields."""
        if mapping is None:
            mapping = {}

        def remap_id(expr_id):
            """Remap an expression ID."""
            if expr_id in mapping:
                return mapping[expr_id]
            return expr_id + offset

        result = []
        for expr in expr_array:
            new_expr = expr.copy()

            # Update the expression's own ID
            if 'i' in new_expr:
                new_expr['i'] = remap_id(new_expr['i'])

            # Update argument list (expressions referenced by this expression)
            if 'a' in new_expr and isinstance(new_expr['a'], list):
                new_expr['a'] = [remap_id(a) if isinstance(a, int) else a for a in new_expr['a']]

            # Update function reference if present
            if 'f' in new_expr and isinstance(new_expr['f'], int):
                new_expr['f'] = remap_id(new_expr['f'])

            result.append(new_expr)

        return result

    # Reindex child expression arrays
    # First, filter out input state declarations (they're duplicates of parent states)
    aes_block_input_ids = set(aes_block_mapping.keys())
    aes_block_exprs_filtered = [e for e in aes_block['a'] if e.get('i') not in aes_block_input_ids]
    print(f"  Filtered {len(aes_block['a']) - len(aes_block_exprs_filtered)} input states from AES_BLOCK")
    aes_block_exprs_reindexed = reindex_expr_array(aes_block_exprs_filtered, parent_expr_offset, aes_block_mapping)

    # Calculate offset for aes128 (max ID from parent + reindexed AES_BLOCK)
    aes_block_max_id = get_max_expr_id(aes_block_exprs_reindexed)
    aes128_expr_offset = aes_block_max_id + 1
    print(f"  AES_BLOCK max expression ID after reindexing: {aes_block_max_id}")
    print(f"  aes128 expression offset: {aes128_expr_offset}")

    # For aes128, adjust mapping to account for both parent and AES_BLOCK mappings
    aes128_mapping_adjusted = {k: (v + parent_expr_offset if v not in aes_block_mapping else aes_block_mapping[v])
                                for k, v in aes128_mapping.items()}
    print(f"  aes128 adjusted mapping: {aes128_mapping_adjusted}")

    # Filter out input state declarations from aes128
    aes128_input_ids = set(aes128_mapping.keys())
    aes128_exprs_filtered = [e for e in aes128['a'] if e.get('i') not in aes128_input_ids]
    print(f"  Filtered {len(aes128['a']) - len(aes128_exprs_filtered)} input states from aes128")

    aes128_exprs_reindexed = reindex_expr_array(aes128_exprs_filtered, aes128_expr_offset, aes128_mapping_adjusted)

    # Create combined expression array with reindexed expressions
    combined_a = parent['a'] + aes_block_exprs_reindexed + aes128_exprs_reindexed

    # Reindex and merge function definitions
    def reindex_functions(func_array, offset, mapping=None):
        """Reindex function definitions."""
        if mapping is None:
            mapping = {}
        if func_array is None:
            return []

        result = []
        for func in func_array:
            new_func = func.copy()
            if 'i' in new_func:
                old_id = new_func['i']
                new_id = mapping.get(old_id, old_id + offset)
                new_func['i'] = new_id
            result.append(new_func)
        return result

    # Merge functions from all layers
    parent_funcs = parent.get('f', [])
    aes_block_funcs_reindexed = reindex_functions(aes_block.get('f', []), parent_expr_offset, aes_block_mapping)
    aes128_funcs_reindexed = reindex_functions(aes128.get('f', []), aes128_expr_offset, aes128_mapping_adjusted)

    combined_f = parent_funcs + aes_block_funcs_reindexed + aes128_funcs_reindexed
    print(f"  Combined functions: {len(parent_funcs)} + {len(aes_block_funcs_reindexed)} + {len(aes128_funcs_reindexed)} = {len(combined_f)}")

    # Re-index expression IDs in the 't' structure
    def reindex_t_structure(t_dict, offset, mapping=None):
        """
        Update expression IDs in an ILA 't' structure.

        Keys that contain expression IDs to offset:
        - 's': state list (array of expression IDs)
        - 'instr': array of instruction dicts (each with 'd' and 'u' fields)
        - 'init': init conditions (array of expression IDs)

        Keys that should NOT be offset:
        - 'n': name
        - 'i', 'f', 'v': internal IDs and other metadata
        """
        if mapping is None:
            mapping = {}

        def remap_expr(e):
            """Remap an expression ID using mapping or offset."""
            if not isinstance(e, int):
                return e
            if e in mapping:
                return mapping[e]
            return e + offset

        result = {}

        for k, v in t_dict.items():
            if k == 's' and isinstance(v, list):
                # State list: array of expression IDs
                result[k] = [remap_expr(e) for e in v]
            elif k == 'instr' and isinstance(v, list):
                # Instruction array: each instruction has 'd' (decode) and 'u' (updates)
                result[k] = [reindex_instruction(instr, offset, mapping) for instr in v]
            elif k == 'init' and isinstance(v, list):
                # Init conditions: array of expression IDs
                result[k] = [remap_expr(e) for e in v]
            elif k == 'i' and isinstance(v, list):
                # Input state list: should be remapped
                result[k] = [remap_expr(e) for e in v]
            elif k == 'c' and isinstance(v, list):
                # Child ILAs: recursively reindex each child
                result[k] = v  # Will handle separately
            else:
                # Other keys like 'n', 'f', 'v' - don't modify
                result[k] = v

        return result

    def reindex_instruction(instr, offset, mapping=None):
        """Update expression IDs in an instruction dict."""
        if mapping is None:
            mapping = {}

        def remap_expr(e):
            """Remap an expression ID using mapping or offset."""
            if not isinstance(e, int):
                return e
            if e in mapping:
                return mapping[e]
            return e + offset

        result = {}

        for k, v in instr.items():
            if k == 'd' and isinstance(v, int):
                # Decode expression ID
                result[k] = remap_expr(v)
            elif k == 'u' and isinstance(v, dict):
                # Updates: dict of state_name -> expression_id
                result[k] = {state: remap_expr(expr_id) for state, expr_id in v.items()}
            else:
                # Other keys like 'n' (name), 'p' (program) - don't modify
                result[k] = v

        return result

    # Re-index AES_BLOCK's 't' structure (states, instructions)
    # Use mapping for input states, offset for local states
    aes_block_t_reindexed = reindex_t_structure(aes_block_t_with_child, parent_expr_offset, aes_block_mapping)

    # Re-index aes128's 't' structure
    # Use the adjusted mapping and aes128 expression offset
    aes128_t_reindexed = reindex_t_structure(aes128_t, aes128_expr_offset, aes128_mapping_adjusted)

    # Update the child reference
    aes_block_t_reindexed['c'] = [aes128_t_reindexed]

    # Also add aes128 as a direct child of parent so parser can find it for inlining
    # (Parser doesn't recursively search grandchildren)
    aes128_t_reindexed_copy = aes128_t_reindexed.copy()
    aes128_t_reindexed_copy['n'] = 'aes128_function'  # Parser looks for this name
    parent_t_with_child['c'] = [aes_block_t_reindexed, aes128_t_reindexed_copy]

    # Wrap children in proper structure (with 'a', 'f', 't' keys) for parser
    aes_block_wrapped = {
        'a': combined_a,  # Share the combined expression array
        'f': combined_f,  # Share the combined functions
        't': aes_block_t_reindexed
    }

    aes128_wrapped = {
        'a': combined_a,  # Share the combined expression array
        'f': combined_f,  # Share the combined functions
        't': aes128_t_reindexed_copy
    }

    combined = {
        'a': combined_a,
        'f': combined_f,
        't': parent_t_with_child,
        'c': [aes_block_wrapped, aes128_wrapped]  # Top-level 'c' with wrapped children
    }

    # Write output
    output_file = 'test_data/aes_full_three_layer.json'
    with open(output_file, 'w') as f:
        json.dump(combined, f, indent=2)

    print(f"\n✓ Created {output_file}")
    print(f"  Structure:")
    print(f"    Parent: {parent['t'].get('n')} with {len(parent['t']['instr'])} instructions")
    print(f"    Child: {aes_block_t_reindexed.get('n')} with {len(aes_block_t_reindexed['instr'])} instructions")
    print(f"    Grandchild: {aes128_t_reindexed.get('n')} with {len(aes128_t_reindexed['instr'])} instructions")
    print(f"  Total expressions: {len(combined_a)}")


if __name__ == '__main__':
    main()
