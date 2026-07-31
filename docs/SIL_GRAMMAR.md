# Safe Intermediate Language (SIL) - Grammar BNF

The SIL is a deliberately constrained, deterministic intermediate representation used for bounded model checking.

## Type System
```bnf
<type> ::= "int" | "bool" | "string" | <array_type>
<array_type> ::= "array" "<" <type> ">"
```

## Expressions
```bnf
<expr> ::= <literal> | <identifier> | <binary_expr> | <unary_expr> | <call_expr> | <array_expr>

<literal> ::= <int_literal> | <bool_literal> | <string_literal>
<int_literal> ::= [0-9]+
<bool_literal> ::= "true" | "false"
<string_literal> ::= '"' [^"]* '"'

<binary_expr> ::= <expr> <binary_op> <expr>
<binary_op> ::= "+" | "-" | "*" | "/" | "==" | "!=" | "<" | "<=" | ">" | ">=" | "and" | "or"

<unary_expr> ::= <unary_op> <expr>
<unary_op> ::= "not" | "-"

<call_expr> ::= <identifier> "(" [ <expr_list> ] ")"
<expr_list> ::= <expr> ("," <expr>)*

<array_expr> ::= "[" [ <expr_list> ] "]" | <identifier> "[" <expr> "]"
```

## Statements
```bnf
<stmt> ::= <assignment_stmt> | <if_stmt> | <while_stmt> | <return_stmt> | <assert_stmt>

<assignment_stmt> ::= <identifier> "=" <expr> ";"
<if_stmt> ::= "if" <expr> "{" <stmt_list> "}" [ "else" "{" <stmt_list> "}" ]

# Critical constraint: All loops must have a literal 'bound' to guarantee termination.
<while_stmt> ::= "while" "(" <expr> ")" "bound" <int_literal> "{" <stmt_list> "}"

<return_stmt> ::= "return" <expr> ";"
<assert_stmt> ::= "assert" <expr> ";"

<stmt_list> ::= <stmt>*
```

## Functions
```bnf
# Recursion is strictly prohibited.
<function> ::= "func" <identifier> "(" [ <param_list> ] ")" "->" <type> "{" <stmt_list> "}"
<param_list> ::= <param> ("," <param>)*
<param> ::= <identifier> ":" <type>
```

## Program
```bnf
<program> ::= <function>*
```
