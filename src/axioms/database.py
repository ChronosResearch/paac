# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.

import yaml
import os

class AxiomDatabase:
    def __init__(self, config_dir="config"):
        self.axioms_path = os.path.join(config_dir, "axioms.yaml")
        self.specs_path = os.path.join(config_dir, "function_specs.yaml")
        self.axioms = self._load_yaml(self.axioms_path)
        self.function_specs = self._load_yaml(self.specs_path)

    def _load_yaml(self, path):
        if not os.path.exists(path):
            return {}
        with open(path, 'r') as f:
            return yaml.safe_load(f)

    def get_axioms_by_category(self, category: str):
        return self.axioms.get(category, {})

    def get_all_axioms(self):
        all_ax = {}
        for cat in self.axioms:
            all_ax.update(self.axioms[cat])
        return all_ax

    def get_function_spec(self, func_name: str):
        return self.function_specs.get(func_name, {})
