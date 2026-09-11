from dataclasses import dataclass, field

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

    # Values to assume for variables the verified function never binds.
    #
    # Needed for axioms over state that only materialises conditionally. The
    # `no_exit` axiom reads `exit_called == 0`, but a function that never takes
    # an exit path never assigns `exit_called`, so the variable is absent from
    # the SSA environment. Without a declared default the axiom cannot be
    # encoded, and the previous behaviour was to silently drop it, which meant
    # the axiom never fired for any function (AUDIT_FINDINGS.md C-03).
    #
    # A default is a claim about the semantics of absence: "if the code never
    # touched this, treat it as 0". That is sound for a sentinel counted up from
    # zero. It is not automatically sound in general, which is why it must be
    # written down per axiom rather than assumed globally by the verifier.
    defaults: dict[str, int] = field(default_factory=dict)

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
            defaults=dict(self.defaults),
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
            raw_defaults = ax.get("defaults", {}) or {}
            if not isinstance(raw_defaults, dict):
                raise AxiomError(
                    f"Axiom '{ax['id']}': 'defaults' must be a mapping of "
                    f"variable name to integer, got {type(raw_defaults).__name__}."
                )
            defaults: dict[str, int] = {}
            for var, value in raw_defaults.items():
                # Rejected rather than coerced. A default silently parsed from
                # the string "0" would still encode, so the axiom would appear
                # to work while resting on a value the author never checked.
                if isinstance(value, bool) or not isinstance(value, int):
                    raise AxiomError(
                        f"Axiom '{ax['id']}': default for '{var}' must be an "
                        f"integer, got {value!r}."
                    )
                defaults[str(var)] = value

            axioms.append(
                Axiom(
                    id=ax["id"],
                    description=ax.get("description", ""),
                    condition=ax["condition"],
                    target_functions=ax.get("target_functions", ["*"]),
                    is_template=ax.get("is_template", False),
                    defaults=defaults,
                )
            )
        return axioms
