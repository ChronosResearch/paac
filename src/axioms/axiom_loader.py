import os

from src.axioms.axiom_parser import Axiom, AxiomParser


class AxiomDatabase:
    def __init__(self):
        self.axioms: dict[str, Axiom] = {}

    def load_file(self, filepath: str):
        with open(filepath, "r") as f:
            content = f.read()
            loaded = AxiomParser.parse(content)
            for ax in loaded:
                self.axioms[ax.id] = ax

    def load_directory(self, dirpath: str):
        if not os.path.isdir(dirpath):
            return
        for file in os.listdir(dirpath):
            if file.endswith((".yaml", ".axioms")):
                self.load_file(os.path.join(dirpath, file))

    def get_axioms_for_function(self, func_name: str) -> list[Axiom]:
        return [
            ax
            for ax in self.axioms.values()
            if "*" in ax.target_functions or func_name in ax.target_functions
        ]
