# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.

import pytest
from src.monitor.code_monitor import CodeMonitor, CodeModification

def test_hallucination_prevention_no_citation():
    monitor = CodeMonitor({"grounding": {"require_source_citations": True}})
    mod = CodeModification(
        func_name="hallucinated_sort",
        old_code="",
        new_code="func hallucinated_sort() -> int { while(x) bound 100 { x = x + 1; } }",
        pre_cond="true",
        post_cond="true",
        source_citation="" # Missing citation
    )
    result = monitor.intercept_modification(mod)
    assert result["status"] == "rejected"
    assert "Missing source citation" in result["error"]

def test_hallucination_prevention_with_citation():
    monitor = CodeMonitor({"grounding": {"require_source_citations": True}})
    mod = CodeModification(
        func_name="quicksort",
        old_code="",
        new_code="func quicksort() -> int { while(x) bound 100 { x = x + 1; } }",
        pre_cond="true",
        post_cond="true",
        source_citation="Algorithm adapted from CLRS." 
    )
    result = monitor.intercept_modification(mod)
    assert result["status"] == "accepted"
