# Copyright (c) 2026 Shashank Kumar. All rights reserved.
import re
from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass
class Token:
    type: str
    value: str
    line: int
    column: int


class SILError(Exception):
    pass


class SILLexer:
    TOKEN_SPEC: ClassVar[list[tuple[str, str]]] = [
        (
            "KEYWORD",
            r"\b(func|return|if|else|while|bound|int|bool|string|array|true|false|and|or|not|assert)\b",
        ),
        ("IDENTIFIER", r"\b[a-zA-Z_][a-zA-Z0-9_]*\b"),
        ("INTEGER", r"\b\d+\b"),
        ("STRING", r'"[\x20-\x21\x23-\x7E]{0,1024}"'),
        ("SYMBOL", r"->|\(|\)|\{|\}|\[|\]|:|;|,"),
        ("OPERATOR", r"==|!=|<=|>=|<|>|\+|-|\*|/|="),
        ("WHITESPACE", r"[ \t]+"),
        ("NEWLINE", r"\n"),
        ("COMMENT", r"#.*"),
        ("ERROR", r"."),  # Step 6: catch-all — must be last.
    ]

    def __init__(self, code: str):
        self.code = code
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """Lex the SIL source string into a flat list of Token objects."""
        tok_regex = "|".join(f"(?P<{name}>{pat})" for name, pat in self.TOKEN_SPEC)
        line_num = 1
        line_start = 0
        for mo in re.finditer(tok_regex, self.code):
            kind = mo.lastgroup
            if kind is None:  # pragma: no cover — guaranteed by regex structure
                continue
            value = mo.group()
            column = mo.start() - line_start
            if kind == "NEWLINE":
                line_start = mo.end()
                line_num += 1
            elif kind in ("WHITESPACE", "COMMENT"):
                continue
            elif kind == "ERROR":
                raise SILError(
                    f"Illegal character {value!r} at line {line_num}, column {column}."
                )
            else:
                self.tokens.append(Token(kind, value, line_num, column))
        return self.tokens


# AST Nodes
@dataclass
class ASTNode:
    pass


@dataclass
class LiteralNode(ASTNode):
    value: Any
    type: str


@dataclass
class IdentifierNode(ASTNode):
    name: str


@dataclass
class BinaryExprNode(ASTNode):
    left: ASTNode
    operator: str
    right: ASTNode


@dataclass
class UnaryExprNode(ASTNode):
    operator: str
    operand: ASTNode


@dataclass
class CallExprNode(ASTNode):
    func_name: str
    args: list[ASTNode]


@dataclass
class ArrayAccessNode(ASTNode):
    array_name: str
    index: ASTNode


@dataclass
class AssignmentStmtNode(ASTNode):
    target: str
    value: ASTNode


@dataclass
class IfStmtNode(ASTNode):
    condition: ASTNode
    then_branch: list[ASTNode]
    else_branch: list[ASTNode]


@dataclass
class WhileStmtNode(ASTNode):
    condition: ASTNode
    bound: int
    body: list[ASTNode]


@dataclass
class ReturnStmtNode(ASTNode):
    value: ASTNode


@dataclass
class AssertStmtNode(ASTNode):
    condition: ASTNode


@dataclass
class ParamNode(ASTNode):
    name: str
    type_name: str


@dataclass
class FuncDefNode(ASTNode):
    name: str
    params: list[ParamNode]
    return_type: str
    body: list[ASTNode]


@dataclass
class ProgramNode(ASTNode):
    functions: list[FuncDefNode]


class SILParser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        """Return the current token without advancing the position, or None at EOF."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consume(
        self,
        expected_type: str | None = None,
        expected_value: str | None = None,
    ) -> Token:
        """Advance past the current token and return it, raising SILError on mismatch."""
        tok = self.peek()
        if not tok:
            raise SILError("Unexpected end of input")
        if expected_type and tok.type != expected_type:
            raise SILError(
                f"Expected token type {expected_type}, got {tok.type} at {tok.line}:{tok.column}"
            )
        if expected_value and tok.value != expected_value:
            raise SILError(
                f"Expected '{expected_value}', got '{tok.value}' at {tok.line}:{tok.column}"
            )
        self.pos += 1
        return tok

    def match(
        self,
        expected_type: str | None = None,
        expected_value: str | None = None,
    ) -> bool:
        """Advance past the current token if it matches; return True on match, False otherwise."""
        tok = self.peek()
        if not tok:
            return False
        if expected_type and tok.type != expected_type:
            return False
        if expected_value and tok.value != expected_value:
            return False
        self.pos += 1
        return True

    def parse_program(self) -> ProgramNode:
        """Parse a complete SIL program (zero or more function definitions) into a ProgramNode."""
        funcs = []
        while self.peek():
            funcs.append(self.parse_function())
        # Step 7: Full call-graph cycle detection (catches mutual recursion).
        self._check_call_graph(funcs)
        return ProgramNode(funcs)

    # ------------------------------------------------------------------
    # Step 7: Call-graph cycle detection
    # ------------------------------------------------------------------

    def _collect_callees(self, node: ASTNode) -> list[str]:
        """Return all function names called anywhere within node."""
        callees: list[str] = []
        if isinstance(node, CallExprNode):
            callees.append(node.func_name)
            for arg in node.args:  # also recurse into arguments
                callees.extend(self._collect_callees(arg))
        elif isinstance(node, FuncDefNode):
            for stmt in node.body:
                callees.extend(self._collect_callees(stmt))
        elif isinstance(node, IfStmtNode):
            callees.extend(self._collect_callees(node.condition))
            for s in node.then_branch:
                callees.extend(self._collect_callees(s))
            for s in node.else_branch:
                callees.extend(self._collect_callees(s))
        elif isinstance(node, WhileStmtNode):
            callees.extend(self._collect_callees(node.condition))
            for s in node.body:
                callees.extend(self._collect_callees(s))
        elif isinstance(node, (AssignmentStmtNode, ReturnStmtNode)):
            callees.extend(self._collect_callees(node.value))
        elif isinstance(node, AssertStmtNode):
            callees.extend(self._collect_callees(node.condition))
        elif isinstance(node, BinaryExprNode):
            callees.extend(self._collect_callees(node.left))
            callees.extend(self._collect_callees(node.right))
        elif isinstance(node, UnaryExprNode):
            callees.extend(self._collect_callees(node.operand))
        return callees

    def _check_call_graph(self, funcs: list[FuncDefNode]) -> None:
        """DFS cycle detection over the full inter-function call graph."""
        graph: dict[str, list[str]] = {f.name: self._collect_callees(f) for f in funcs}
        visited: set = set()
        in_stack: set = set()

        def dfs(name: str, path: list[str]) -> None:
            """Depth-first search helper for call-graph cycle detection."""
            if name not in graph:
                return  # call to external / stdlib — not our concern here
            if name in in_stack:
                cycle = " -> ".join(path + [name])
                raise SILError(f"Recursion cycle detected: {cycle}")
            if name in visited:
                return
            visited.add(name)
            in_stack.add(name)
            for callee in graph[name]:
                dfs(callee, path + [name])
            in_stack.discard(name)

        for func in funcs:
            dfs(func.name, [])

    # kept for any external callers that may reference it directly
    def _check_recursion(self, node: ASTNode, current_func: str) -> None:
        pass  # superseded by _check_call_graph

    def parse_function(self) -> FuncDefNode:
        """Parse a single SIL function definition into a FuncDefNode."""
        self.consume("KEYWORD", "func")
        name = self.consume("IDENTIFIER").value
        self.consume("SYMBOL", "(")
        params = []
        if not self.match("SYMBOL", ")"):
            params.append(self.parse_param())
            while self.match("SYMBOL", ","):
                params.append(self.parse_param())
            self.consume("SYMBOL", ")")
        self.consume("SYMBOL", "->")
        ret_type = self.consume("KEYWORD").value
        self.consume("SYMBOL", "{")
        body = []
        while not self.match("SYMBOL", "}"):
            body.append(self.parse_stmt())
        return FuncDefNode(name, params, ret_type, body)

    def parse_param(self) -> ParamNode:
        """Parse a single parameter declaration (name: type) into a ParamNode."""
        name = self.consume("IDENTIFIER").value
        self.consume("SYMBOL", ":")
        type_name = self.consume("KEYWORD").value
        return ParamNode(name, type_name)

    def parse_stmt(self) -> ASTNode:
        """Dispatch to the appropriate statement parser based on the current token."""
        tok = self.peek()
        if tok is None:
            raise SILError("Unexpected end of input in statement")
        if tok.type == "KEYWORD" and tok.value == "if":
            return self.parse_if()
        elif tok.type == "KEYWORD" and tok.value == "while":
            return self.parse_while()
        elif tok.type == "KEYWORD" and tok.value == "return":
            return self.parse_return()
        elif tok.type == "KEYWORD" and tok.value == "assert":
            return self.parse_assert()
        else:
            return self.parse_assignment()

    def parse_if(self) -> IfStmtNode:
        """Parse an if/else statement into an IfStmtNode."""
        self.consume("KEYWORD", "if")
        cond = self.parse_expr()
        self.consume("SYMBOL", "{")
        then_branch = []
        while not self.match("SYMBOL", "}"):
            then_branch.append(self.parse_stmt())
        else_branch = []
        if self.match("KEYWORD", "else"):
            self.consume("SYMBOL", "{")
            while not self.match("SYMBOL", "}"):
                else_branch.append(self.parse_stmt())
        return IfStmtNode(cond, then_branch, else_branch)

    def parse_while(self) -> WhileStmtNode:
        """Parse a bounded while loop into a WhileStmtNode."""
        self.consume("KEYWORD", "while")
        self.consume("SYMBOL", "(")
        cond = self.parse_expr()
        self.consume("SYMBOL", ")")
        self.consume("KEYWORD", "bound")
        bound_tok = self.consume("INTEGER")
        bound = int(bound_tok.value)
        if bound <= 0:
            raise SILError("Loop bound must be positive")
        self.consume("SYMBOL", "{")
        body = []
        while not self.match("SYMBOL", "}"):
            body.append(self.parse_stmt())
        return WhileStmtNode(cond, bound, body)

    def parse_return(self) -> ReturnStmtNode:
        """Parse a return statement into a ReturnStmtNode."""
        self.consume("KEYWORD", "return")
        val = self.parse_expr()
        self.consume("SYMBOL", ";")
        return ReturnStmtNode(val)

    def parse_assert(self) -> AssertStmtNode:
        """Parse an assert statement into an AssertStmtNode."""
        self.consume("KEYWORD", "assert")
        val = self.parse_expr()
        self.consume("SYMBOL", ";")
        return AssertStmtNode(val)

    def parse_assignment(self) -> AssignmentStmtNode:
        """Parse a variable assignment statement into an AssignmentStmtNode."""
        target = self.consume("IDENTIFIER").value
        self.consume("OPERATOR", "=")
        val = self.parse_expr()
        self.consume("SYMBOL", ";")
        return AssignmentStmtNode(target, val)

    def parse_expr(self) -> ASTNode:
        """Entry point for expression parsing; delegates to parse_binary_expr."""
        return self.parse_binary_expr(0)

    def parse_binary_expr(self, precedence: int) -> ASTNode:
        """Pratt-style binary expression parser; handles operators by precedence level."""
        # Simple Pratt-like parsing for binary ops
        left = self.parse_primary()
        while True:
            tok = self.peek()
            if not tok or tok.type not in ("OPERATOR", "KEYWORD"):
                break
            if tok.value not in (
                "+",
                "-",
                "*",
                "/",
                "==",
                "!=",
                "<",
                "<=",
                ">",
                ">=",
                "and",
                "or",
            ):
                break
            op_prec = self._precedence(tok.value)
            if op_prec < precedence:
                break
            self.consume()
            right = self.parse_binary_expr(op_prec + 1)
            left = BinaryExprNode(left, tok.value, right)
        return left

    def _precedence(self, op: str) -> int:
        if op in ("and", "or"):
            return 1
        if op in ("==", "!=", "<", "<=", ">", ">="):
            return 2
        if op in ("+", "-"):
            return 3
        if op in ("*", "/"):
            return 4
        return 0

    def parse_primary(self) -> ASTNode:
        """Parse a primary expression: literal, identifier, array access, call, or parenthesised expr."""
        tok = self.peek()
        if tok is None:
            raise SILError("Unexpected end of input in expression")
        # Unary 'not'
        if tok.type == "KEYWORD" and tok.value == "not":
            self.consume()
            operand = self.parse_primary()
            return UnaryExprNode("not", operand)
        # Unary minus
        if tok.type == "OPERATOR" and tok.value == "-":
            self.consume()
            operand = self.parse_primary()
            return UnaryExprNode("-", operand)
        if tok.type == "INTEGER":
            self.consume()
            return LiteralNode(int(tok.value), "int")
        if tok.type == "KEYWORD" and tok.value in ("true", "false"):
            self.consume()
            return LiteralNode(tok.value == "true", "bool")
        if tok.type == "STRING":
            self.consume()
            return LiteralNode(tok.value[1:-1], "string")
        if tok.type == "IDENTIFIER":
            self.consume()
            if self.match("SYMBOL", "("):
                args = []
                if not self.match("SYMBOL", ")"):
                    args.append(self.parse_expr())
                    while self.match("SYMBOL", ","):
                        args.append(self.parse_expr())
                    self.consume("SYMBOL", ")")
                return CallExprNode(tok.value, args)
            if self.match("SYMBOL", "["):
                index = self.parse_expr()
                self.consume("SYMBOL", "]")
                return ArrayAccessNode(tok.value, index)
            return IdentifierNode(tok.value)
        if self.match("SYMBOL", "("):
            expr = self.parse_expr()
            self.consume("SYMBOL", ")")
            return expr
        raise SILError(f"Unexpected token {tok.value} at {tok.line}:{tok.column}")


class SILTypeChecker:
    def __init__(self, ast: ProgramNode):
        self.ast = ast
        self.functions: dict[str, FuncDefNode] = {}
        self.current_env: dict[str, str] = {}

    def check(self):
        """Type-check the AST: detect duplicate functions, undefined variables, and type mismatches."""
        for func in self.ast.functions:
            if func.name in self.functions:
                raise SILError(f"Duplicate function: {func.name}")
            self.functions[func.name] = func

        for func in self.ast.functions:
            self._check_function(func)

    def _check_function(self, func: FuncDefNode):
        # H-02: detect duplicate parameter names
        seen_params: set[str] = set()
        for p in func.params:
            if p.name in seen_params:
                raise SILError(f"Duplicate parameter name '{p.name}' in function '{func.name}'")
            seen_params.add(p.name)
        self.current_env = {p.name: p.type_name for p in func.params}
        for stmt in func.body:
            self._check_stmt(stmt, func.return_type)
        # H-03: warn when no return statement is present
        has_return = any(isinstance(s, ReturnStmtNode) for s in func.body)
        if not has_return and func.return_type != "bool":
            import warnings
            warnings.warn(
                f"Function '{func.name}' has no return statement.",
                SyntaxWarning,
                stacklevel=2,
            )

    def _check_stmt(self, stmt: ASTNode, return_type: str):
        if isinstance(stmt, AssignmentStmtNode):
            val_type = self._check_expr(stmt.value)
            if stmt.target in self.current_env:
                if self.current_env[stmt.target] != val_type:
                    raise SILError(
                        f"Type mismatch in assignment to {stmt.target}: {val_type} != {self.current_env[stmt.target]}"
                    )
            else:
                self.current_env[stmt.target] = val_type
        elif isinstance(stmt, IfStmtNode):
            cond_type = self._check_expr(stmt.condition)
            if cond_type != "bool":
                raise SILError(f"If condition must be bool, got {cond_type}")
            for s in stmt.then_branch:
                self._check_stmt(s, return_type)
            for s in stmt.else_branch:
                self._check_stmt(s, return_type)
        elif isinstance(stmt, WhileStmtNode):
            cond_type = self._check_expr(stmt.condition)
            if cond_type != "bool":
                raise SILError(f"While condition must be bool, got {cond_type}")
            for s in stmt.body:
                self._check_stmt(s, return_type)
        elif isinstance(stmt, ReturnStmtNode):
            val_type = self._check_expr(stmt.value)
            if val_type != return_type:
                raise SILError(
                    f"Return type mismatch: expected {return_type}, got {val_type}"
                )
        elif isinstance(stmt, AssertStmtNode):
            cond_type = self._check_expr(stmt.condition)
            if cond_type != "bool":
                raise SILError(f"Assert condition must be bool, got {cond_type}")

    def _check_expr(self, expr: ASTNode) -> str:
        if isinstance(expr, LiteralNode):
            return expr.type
        elif isinstance(expr, IdentifierNode):
            if expr.name not in self.current_env:
                raise SILError(f"Undefined variable: {expr.name}")
            return self.current_env[expr.name]
        elif isinstance(expr, BinaryExprNode):
            l_type = self._check_expr(expr.left)
            r_type = self._check_expr(expr.right)
            if expr.operator in ("+", "-", "*", "/", "<", "<=", ">", ">="):
                if l_type != "int" or r_type != "int":
                    raise SILError(f"Operator {expr.operator} requires int operands")
                return "bool" if expr.operator in ("<", "<=", ">", ">=") else "int"
            elif expr.operator in ("and", "or"):
                if l_type != "bool" or r_type != "bool":
                    raise SILError(f"Operator {expr.operator} requires bool operands")
                return "bool"
            elif expr.operator in ("==", "!="):
                if l_type != r_type:
                    raise SILError(
                        f"Operator {expr.operator} requires operands of same type"
                    )
                return "bool"
        elif isinstance(expr, CallExprNode):
            if expr.func_name not in self.functions:
                raise SILError(f"Undefined function: {expr.func_name}")
            func = self.functions[expr.func_name]
            if len(expr.args) != len(func.params):
                raise SILError(f"Arity mismatch in call to {expr.func_name}")
            for arg, param in zip(expr.args, func.params):
                arg_type = self._check_expr(arg)
                if arg_type != param.type_name:
                    raise SILError(
                        f"Argument type mismatch: expected {param.type_name}, got {arg_type}"
                    )
            return func.return_type
        elif isinstance(expr, UnaryExprNode):
            operand_type = self._check_expr(expr.operand)
            if expr.operator == "not":
                if operand_type != "bool":
                    raise SILError(
                        f"Operator 'not' requires bool operand, got {operand_type}"
                    )
                return "bool"
            if expr.operator == "-":
                if operand_type != "int":
                    raise SILError(
                        f"Unary '-' requires int operand, got {operand_type}"
                    )
                return "int"
            raise SILError(f"Unknown unary operator: {expr.operator}")
        elif isinstance(expr, ArrayAccessNode):
            if expr.array_name not in self.current_env:
                raise SILError(f"Undefined variable: {expr.array_name}")
            idx_type = self._check_expr(expr.index)
            if idx_type != "int":
                raise SILError(f"Array index must be int, got {idx_type}")
            return "int"  # arrays are int arrays
        raise SILError(f"Type checking not implemented for {type(expr).__name__}")


@dataclass
class BasicBlock:
    id: int
    statements: list[ASTNode]  # only StatementNodes (Assignment, Return, Assert)
    successors: list["BasicBlock"]
    branch_condition: "ASTNode | None" = None  # R-5: condition stored separately


class SILToIRCompiler:
    def __init__(self, ast: ProgramNode):
        self.ast = ast
        self.block_counter = 0

    def compile(self) -> dict[str, BasicBlock]:
        """Build a CFG (basic-block map) for every function in the AST."""
        cfgs = {}
        for func in self.ast.functions:
            cfgs[func.name] = self._compile_function(func)
        return cfgs

    def _new_block(self) -> BasicBlock:
        self.block_counter += 1
        return BasicBlock(self.block_counter, [], [])

    def _compile_function(self, func: FuncDefNode) -> BasicBlock:
        entry_block = self._new_block()
        current_block = entry_block
        for stmt in func.body:
            current_block = self._compile_stmt(stmt, current_block)
        return entry_block

    def _compile_stmt(self, stmt: ASTNode, current_block: BasicBlock) -> BasicBlock:
        if isinstance(stmt, (AssignmentStmtNode, ReturnStmtNode, AssertStmtNode)):
            current_block.statements.append(stmt)
            return current_block
        elif isinstance(stmt, IfStmtNode):
            # R-5: store the branch condition in the dedicated field, not statements.
            then_block = self._new_block()
            else_block = self._new_block()
            merge_block = self._new_block()

            current_block.branch_condition = stmt.condition
            current_block.successors.extend([then_block, else_block])

            t_curr = then_block
            for s in stmt.then_branch:
                t_curr = self._compile_stmt(s, t_curr)
            t_curr.successors.append(merge_block)

            e_curr = else_block
            for s in stmt.else_branch:
                e_curr = self._compile_stmt(s, e_curr)
            e_curr.successors.append(merge_block)

            return merge_block
        elif isinstance(stmt, WhileStmtNode):
            header = self._new_block()
            body = self._new_block()
            exit_block = self._new_block()

            current_block.successors.append(header)
            # R-5: loop condition goes in branch_condition, not statements.
            header.branch_condition = stmt.condition
            header.successors.extend([body, exit_block])

            b_curr = body
            for s in stmt.body:
                b_curr = self._compile_stmt(s, b_curr)
            b_curr.successors.append(header)

            return exit_block
        return current_block


class SILCompiler:
    def compile(self, code: str) -> tuple[ProgramNode, dict[str, BasicBlock]]:
        """Lex, parse, type-check, and CFG-compile a SIL source string.

        Args:
            code: Raw SIL source text.

        Returns:
            (ProgramNode, cfg_map) where cfg_map maps function names to BasicBlock dicts.

        Raises:
            SILError: On any lexical, parse, or type error.
        """
        lexer = SILLexer(code)
        tokens = lexer.tokenize()
        parser = SILParser(tokens)
        ast = parser.parse_program()

        checker = SILTypeChecker(ast)
        checker.check()

        ir_compiler = SILToIRCompiler(ast)
        cfgs = ir_compiler.compile()

        return ast, cfgs
