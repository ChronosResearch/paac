# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.

from .exceptions import SafetyViolationError

class SILRuntime:
    def __init__(self, config):
        self.max_memory = config.get("max_memory_bytes", 4294967296)
        self.allocated = 0
        self.io_whitelist = config.get("safe_io_whitelist", [])

    def allocate(self, size: int):
        if self.allocated + size > self.max_memory:
            raise SafetyViolationError("Memory limit exceeded.")
        self.allocated += size

    def execute_call(self, func_name: str, args: list):
        if func_name not in self.io_whitelist and not self._is_stdlib(func_name):
            raise SafetyViolationError(f"Unauthorized function call: {func_name}")
        return True

    def _is_stdlib(self, func_name: str):
        return func_name in ["array_len", "array_map", "array_filter", "array_concat", "max", "min"]

    # Stdlib implementations
    def array_len(self, arr):
        return len(arr)
        
    def max(self, a, b):
        return max(a, b)
        
    def min(self, a, b):
        return min(a, b)
        
    def array_map(self, arr, func):
        return [func(x) for x in arr]
        
    def array_filter(self, arr, pred):
        return [x for x in arr if pred(x)]
        
    def array_concat(self, arr1, arr2):
        return arr1 + arr2
