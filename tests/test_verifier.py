# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.
import pytest
from src.core.verifier import Verifier
from src.core.exceptions import VerificationError

def test_verifier_safe():
    v = Verifier({"verification_timeout_ms": 1000, "constant_verification_time_padding_ms": 10})
    result = v.verify("test", "ast", "pre_cond")
    assert result["safe"] == True
