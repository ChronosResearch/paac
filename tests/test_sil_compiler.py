# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.
import pytest
from src.core.sil_compiler import SILCompiler
from src.core.exceptions import CompilationError

def test_sil_compiler_valid():
    code = "func sort() -> int { while(x) bound 100 { x = x + 1; } }"
    compiler = SILCompiler()
    ast = compiler.compile(code)
    assert ast is not None

def test_sil_compiler_invalid():
    code = "func sort() -> int { while(x) { x = x + 1; } }" # missing bound
    compiler = SILCompiler()
    with pytest.raises(CompilationError):
        compiler.compile(code)
