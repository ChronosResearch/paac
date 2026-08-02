import dataclasses
import json

from src.axioms.axiom_loader import AxiomDatabase
from src.core.sil_compiler import SILCompiler, SILError
from src.core.verifier import BoundedModelChecker, VerificationError


@dataclasses.dataclass
class CodeModification:
    file_path: str
    target_function: str
    proposed_sil: str
    author: str

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self))

    @staticmethod
    def from_json(data: str) -> "CodeModification":
        return CodeModification(**json.loads(data))


class Interceptor:
    def __init__(self, axiom_db: AxiomDatabase):
        self.compiler = SILCompiler()
        self.bmc = BoundedModelChecker()
        self.axiom_db = axiom_db

    def intercept(self, mod: CodeModification) -> bool:
        """
        Intercepts a proposed code modification.
        Returns True if safe and executed, False if rejected.
        """
        try:
            # Step 38: Sandbox Environment (Compile SIL AST safely)
            ast, _ = self.compiler.compile(mod.proposed_sil)

            # Step 39: Verification Pipeline
            axioms = self.axiom_db.get_axioms_for_function(mod.target_function)

            safe, ce = self.bmc.verify(ast, axioms)
            if safe:
                self._apply_modification(mod)
                return True
            else:
                self._log_rejection(mod, str(ce) if ce else "")
                return False

        except (SILError, VerificationError) as e:
            self._log_rejection(mod, str(e))
            return False
        except Exception:
            # Auto-rollback on unexpected failures
            self._rollback(mod)
            return False

    def _apply_modification(self, mod: CodeModification):
        # In a real environment, this applies the patch safely.
        pass

    def _log_rejection(self, mod: CodeModification, reason: str):
        # In a real environment, logs to audit stream
        pass

    def _rollback(self, mod: CodeModification):
        # Auto-rollback state
        pass
