# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.

import pytest
from src.core.sil_compiler import SILCompiler

def test_stdlib_parsing():
    code = """
    func process_array() -> int {
        let size: int = arr.length;
        let max_val: int = max(1, 2);
        let min_val: int = min(1, 2);
        let mapped: array<int, 10> = arr.map(double);
        let filtered: array<int, 10> = arr.filter(is_positive);
        let combined: array<int, 20> = arr.concat(mapped);
        return size;
    }
    """
    compiler = SILCompiler()
    ast = compiler.compile(code)
    assert ast is not None
