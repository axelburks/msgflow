from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal


FIELD_MAP: dict[str, str] = {
    # message_records columns
    "id":                  "mr.id",
    "kind":                "mr.kind",
    "cursor_value":        "mr.cursor_value",
    "timestamp":           "mr.timestamp",
    "time_str":            "mr.time_str",
    "sender":              "mr.sender",
    "receiver":            "mr.receiver",
    "text":                "mr.text",
    "title":               "mr.title",
    "subtitle":            "mr.subtitle",
    "body":                "mr.body",
    "msg":                 "mr.msg",
    "created_at":          "mr.created_at",
    # run_records columns
    "run_id":              "rr.id",
    "code":                "rr.code",
    "trigger":             "rr.trigger_type",
    "trigger_type":        "rr.trigger_type",
    "status":              "rr.status",
    "matched_rule_count":  "rr.matched_rule_count",
    "sent_dest_count":     "rr.sent_dest_count",
    "success_dest_count":  "rr.success_dest_count",
    "failed_dest_count":   "rr.failed_dest_count",
    "trace":               "rr.trace",
    "run_created_at":      "rr.created_at",
}

DEFAULT_FIELD = "text"
TokenType = Literal[
    "WORD",
    "STRING",
    "COLON",
    "LPAREN",
    "RPAREN",
    "PIPE",
    "AND",
    "OR",
    "NOT",
    "DASH",
    "BANG",
    "EQ",
    "TILDE",
    "EOF",
]
TermOp = Literal["like", "nlike", "eq", "ne", "regex", "nregex"]


@dataclass(frozen=True)
class Token:
    type: TokenType
    value: str
    pos: int


@dataclass(frozen=True)
class Clause:
    field: str
    op: TermOp
    value: str


@dataclass(frozen=True)
class Not:
    expr: Expr


@dataclass(frozen=True)
class And:
    items: tuple[Expr, ...]


@dataclass(frozen=True)
class Or:
    items: tuple[Expr, ...]


Expr = Clause | Not | And | Or


class Lexer:
    def __init__(self, query: str) -> None:
        self.query = query
        self.i = 0
        self.n = len(query)

    def scan(self) -> list[Token]:
        tokens: list[Token] = []
        while self.i < self.n:
            ch = self.query[self.i]
            if ch.isspace():
                self.i += 1
                continue
            if ch in ":()|!~= -":
                tokens.append(self._scan_symbol(ch))
                continue
            if ch in "'\"":
                tokens.append(self._scan_string(ch))
                continue
            tokens.append(self._scan_word())
        tokens.append(Token("EOF", "", self.n))
        return tokens

    def _scan_symbol(self, ch: str) -> Token:
        pos = self.i
        self.i += 1
        token_map: dict[str, TokenType] = {
            ":": "COLON",
            "(": "LPAREN",
            ")": "RPAREN",
            "|": "PIPE",
            "!": "BANG",
            "~": "TILDE",
            "=": "EQ",
            "-": "DASH",
        }
        return Token(token_map[ch], ch, pos)

    def _scan_string(self, quote: str) -> Token:
        start = self.i
        self.i += 1
        buf: list[str] = []
        while self.i < self.n:
            ch = self.query[self.i]
            if ch == quote:
                self.i += 1
                return Token("STRING", "".join(buf), start)
            if ch == "\\" and self.i + 1 < self.n:
                nxt = self.query[self.i + 1]
                if nxt in (quote, "\\"):
                    buf.append(nxt)
                elif nxt == "n":
                    buf.append("\n")
                elif nxt == "t":
                    buf.append("\t")
                else:
                    buf.append(ch)
                    buf.append(nxt)
                self.i += 2
                continue
            buf.append(ch)
            self.i += 1
        raise ValueError(f"unclosed {quote} quote at position {start}")

    def _scan_word(self) -> Token:
        start = self.i
        buf: list[str] = []
        special = set(":()|!~= -'\"")
        while self.i < self.n:
            ch = self.query[self.i]
            if ch.isspace() or ch in special:
                break
            if ch == "\\" and self.i + 1 < self.n:
                buf.append(self.query[self.i + 1])
                self.i += 2
                continue
            buf.append(ch)
            self.i += 1
        value = "".join(buf)
        upper_value = value.upper()
        if upper_value in {"AND", "OR", "NOT"}:
            return Token(upper_value, value, start)  # type: ignore[arg-type]
        return Token("WORD", value, start)


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.i = 0

    def parse(self, default_field: str = DEFAULT_FIELD) -> Expr | None:
        expr = self._parse_or(default_field)
        if self._current().type != "EOF":
            token = self._current()
            raise ValueError(f"unexpected token {token.value!r} at position {token.pos}")
        return expr

    def _parse_or(self, default_field: str) -> Expr | None:
        items = [self._parse_and(default_field)]
        while self._match("PIPE", "OR"):
            right = self._parse_and(default_field)
            if right is None:
                raise ValueError("missing expression after OR")
            items.append(right)
        return self._combine_or([item for item in items if item is not None])

    def _parse_and(self, default_field: str) -> Expr | None:
        items: list[Expr] = []
        first = self._parse_unary(default_field)
        if first is not None:
            items.append(first)
        while True:
            if self._match("AND"):
                right = self._parse_unary(default_field)
                if right is None:
                    raise ValueError("missing expression after AND")
                items.append(right)
                continue
            if self._starts_unary():
                right = self._parse_unary(default_field)
                if right is not None:
                    items.append(right)
                continue
            break
        return self._combine_and(items)

    def _parse_unary(self, default_field: str) -> Expr | None:
        if self._match("NOT", "DASH"):
            expr = self._parse_unary(default_field)
            if expr is None:
                raise ValueError("missing expression after NOT")
            return Not(expr)
        if self._current().type == "BANG" and self._bang_starts_not():
            self._advance()
            expr = self._parse_unary(default_field)
            if expr is None:
                raise ValueError("missing expression after NOT")
            return Not(expr)
        return self._parse_primary(default_field)

    def _parse_primary(self, default_field: str) -> Expr | None:
        if self._current().type in {"EOF", "RPAREN", "PIPE", "OR", "AND"}:
            return None
        if self._match("LPAREN"):
            expr = self._parse_or(default_field)
            self._expect("RPAREN", "missing closing parenthesis")
            if expr is None:
                raise ValueError("empty parenthesized expression")
            return expr
        if self._current().type in {"BANG", "EQ", "TILDE"}:
            return self._parse_operator_value(default_field)
        if self._current().type in {"WORD", "STRING"}:
            token = self._advance()
            if token.type == "WORD" and self._match("COLON"):
                return self._parse_field_expr(token.value.lower())
            if token.value == "":
                raise ValueError(f"empty value for field {default_field!r}")
            self._validate_field(default_field)
            return Clause(default_field, "like", token.value)
        token = self._current()
        raise ValueError(f"unexpected token {token.value!r} at position {token.pos}")

    def _parse_field_expr(self, field: str) -> Expr:
        self._validate_field(field)
        if self._match("LPAREN"):
            expr = self._parse_or(field)
            self._expect("RPAREN", f"missing closing parenthesis for field {field!r}")
            if expr is None:
                raise ValueError(f"empty grouped value for field {field!r}")
            return expr
        return self._parse_operator_value(field)

    def _parse_operator_value(self, field: str) -> Clause:
        op: TermOp = "like"
        if self._match("BANG"):
            if self._match("TILDE"):
                op = "nregex"
            elif self._match("EQ"):
                op = "ne"
            else:
                op = "nlike"
        elif self._match("TILDE"):
            op = "regex"
        elif self._match("EQ"):
            op = "eq"
        value = self._parse_value(field)
        return Clause(field, op, value)

    def _parse_value(self, field: str) -> str:
        token = self._current()
        if token.type not in {"WORD", "STRING"}:
            raise ValueError(f"empty value for field {field!r}")
        self._advance()
        if token.value == "":
            raise ValueError(f"empty value for field {field!r}")
        return token.value

    def _starts_unary(self) -> bool:
        return self._current().type in {
            "WORD",
            "STRING",
            "LPAREN",
            "NOT",
            "DASH",
            "BANG",
            "EQ",
            "TILDE",
        }

    def _bang_starts_not(self) -> bool:
        next_token = (
            self.tokens[self.i + 1]
            if self.i + 1 < len(self.tokens)
            else Token("EOF", "", self._current().pos)
        )
        after_next = (
            self.tokens[self.i + 2]
            if self.i + 2 < len(self.tokens)
            else Token("EOF", "", self._current().pos)
        )
        return next_token.type in {"LPAREN", "NOT", "DASH", "BANG"} or (
            next_token.type == "WORD" and after_next.type == "COLON"
        )

    def _current(self) -> Token:
        return self.tokens[self.i]

    def _advance(self) -> Token:
        token = self.tokens[self.i]
        self.i += 1
        return token

    def _match(self, *types: TokenType) -> bool:
        if self._current().type in types:
            self.i += 1
            return True
        return False

    def _expect(self, token_type: TokenType, message: str) -> Token:
        if self._current().type != token_type:
            raise ValueError(message)
        return self._advance()

    def _validate_field(self, field: str) -> None:
        if field not in FIELD_MAP:
            raise ValueError(f"unknown field: {field!r}")

    def _combine_and(self, items: list[Expr]) -> Expr | None:
        if not items:
            return None
        if len(items) == 1:
            return items[0]
        flattened: list[Expr] = []
        for item in items:
            if isinstance(item, And):
                flattened.extend(item.items)
            else:
                flattened.append(item)
        return And(tuple(flattened))

    def _combine_or(self, items: list[Expr]) -> Expr | None:
        if not items:
            return None
        if len(items) == 1:
            return items[0]
        flattened: list[Expr] = []
        for item in items:
            if isinstance(item, Or):
                flattened.extend(item.items)
            else:
                flattened.append(item)
        return Or(tuple(flattened))


def tokenize(query: str) -> list[str]:
    return [token.value for token in Lexer(query).scan() if token.type != "EOF"]


def parse_query(query: str) -> Expr | None:
    if not query or not query.strip():
        return None
    return Parser(Lexer(query).scan()).parse()


def iter_clauses(expr: Expr | None) -> Iterable[Clause]:
    if expr is None:
        return
    if isinstance(expr, Clause):
        yield expr
    elif isinstance(expr, Not):
        yield from iter_clauses(expr.expr)
    elif isinstance(expr, (And, Or)):
        for item in expr.items:
            yield from iter_clauses(item)


def compile_expression(expr: Expr | None) -> tuple[str, list[str]]:
    if expr is None:
        return "", []
    if isinstance(expr, Clause):
        return _compile_clause(expr)
    if isinstance(expr, Not):
        return _compile_not(expr.expr)
    if isinstance(expr, And):
        return _compile_joined("AND", expr.items)
    if isinstance(expr, Or):
        return _compile_joined("OR", expr.items)
    raise ValueError(f"unknown expression: {expr!r}")


def compile_clauses(clauses: Iterable[Clause]) -> tuple[str, list[str]]:
    return _compile_joined("AND", tuple(clauses))


def _compile_joined(operator: str, items: Iterable[Expr]) -> tuple[str, list[str]]:
    sql_parts: list[str] = []
    params: list[str] = []
    for item in items:
        sql, item_params = compile_expression(item)
        if not sql:
            continue
        sql_parts.append(f"({sql})")
        params.extend(item_params)
    return f" {operator} ".join(sql_parts), params


def _compile_not(expr: Expr) -> tuple[str, list[str]]:
    if isinstance(expr, Clause):
        inverse: dict[TermOp, TermOp] = {
            "like": "nlike",
            "nlike": "like",
            "eq": "ne",
            "ne": "eq",
            "regex": "nregex",
            "nregex": "regex",
        }
        return _compile_clause(Clause(expr.field, inverse[expr.op], expr.value))
    if isinstance(expr, Not):
        return compile_expression(expr.expr)
    if isinstance(expr, And):
        return _compile_joined("OR", tuple(Not(item) for item in expr.items))
    if isinstance(expr, Or):
        return _compile_joined("AND", tuple(Not(item) for item in expr.items))
    raise ValueError(f"unknown expression: {expr!r}")


def _compile_clause(c: Clause) -> tuple[str, list[str]]:
    col = FIELD_MAP[c.field]
    if c.op == "like":
        return f"{col} LIKE ?", [f"%{c.value}%"]
    if c.op == "nlike":
        return f"({col} IS NULL OR {col} NOT LIKE ?)", [f"%{c.value}%"]
    if c.op == "eq":
        return f"{col} = ?", [c.value]
    if c.op == "ne":
        return f"({col} IS NULL OR {col} <> ?)", [c.value]
    if c.op == "regex":
        _validate_regex(c)
        return f"{col} REGEXP ?", [c.value]
    if c.op == "nregex":
        _validate_regex(c)
        return f"({col} IS NULL OR NOT ({col} REGEXP ?))", [c.value]
    raise ValueError(f"unknown operator {c.op!r} for field {c.field!r}")


def _validate_regex(clause: Clause) -> None:
    try:
        re.compile(clause.value)
    except re.error as e:
        raise ValueError(f"invalid regex for {clause.field!r}: {e}") from e


def build_query_sql(query: str | None) -> tuple[str, list[str]]:
    expr = parse_query(query or "")
    return compile_expression(expr)
