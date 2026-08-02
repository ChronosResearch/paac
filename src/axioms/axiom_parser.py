from dataclasses import dataclass

import yaml


class AxiomError(Exception):
    pass


@dataclass
class Axiom:
    id: str
    description: str
    condition: str
    target_functions: list[str]
    is_template: bool = False

    def apply_template(self, **kwargs) -> "Axiom":
        if not self.is_template:
            return self
        cond = self.condition
        for k, v in kwargs.items():
            cond = cond.replace(f"{{{k}}}", str(v))
        return Axiom(
            f"{self.id}_{kwargs.get('name', 'instance')}",
            self.description,
            cond,
            self.target_functions,
        )


class AxiomParser:
    @staticmethod
    def parse(yaml_content: str) -> list[Axiom]:
        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise AxiomError(f"Invalid YAML: {e}")

        axioms: list[Axiom] = []
        if not data or "axioms" not in data:
            return axioms

        for ax in data["axioms"]:
            if "id" not in ax or "condition" not in ax:
                raise AxiomError("Axiom must contain 'id' and 'condition'")
            axioms.append(
                Axiom(
                    id=ax["id"],
                    description=ax.get("description", ""),
                    condition=ax["condition"],
                    target_functions=ax.get("target_functions", ["*"]),
                    is_template=ax.get("is_template", False),
                )
            )
        return axioms
