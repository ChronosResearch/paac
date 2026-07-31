# SIL Architecture

The Safe Intermediate Language (SIL) is a restricted subset of imperative programming designed specifically for bounded model checking.

## Components
1. **Lexer**: Tokenizes the raw SIL string. Rejects invalid tokens immediately.
2. **Parser**: A recursive descent parser that builds an Abstract Syntax Tree (AST). It enforces the prohibition of recursion.
3. **Type Checker**: Performs static analysis to ensure type safety.
4. **IR Compiler**: Translates the AST into a Control Flow Graph (CFG) of Basic Blocks, which is used by the Z3 Bounded Model Checker.
5. **Runtime**: A bounded interpreter for evaluating SIL code directly, ensuring loops do not exceed their declared literal bounds.

## Key Safety Invariants
- **No Recursion**: Enforced at the parsing stage. Any function calling itself (or mutually recursive) throws an error.
- **Bounded Loops**: Every `while` loop must specify a `bound <literal>`. The runtime and verifier enforce this bound strictly.
- **Strong Typing**: No implicit casting.
