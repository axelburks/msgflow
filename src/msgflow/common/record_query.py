import re
from dataclasses import dataclass
from typing import Iterable


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


@dataclass(frozen=True)
class Clause:
    field: str
    op: str
    value: str


def tokenize(query: str) -> list[str]:
    tokens: list[str] = []
    i, n = 0, len(query)
    while i < n:
        while i < n and query[i].isspace():
            i += 1
        if i >= n:
            break
        buf: list[str] = []
        while i < n and not query[i].isspace():
            ch = query[i]
            if ch == "'":
                i += 1
                while i < n and query[i] != "'":
                    buf.append(query[i])
                    i += 1
                if i < n:
                    i += 1
            elif ch == "\\" and i + 1 < n:
                buf.append(query[i + 1])
                i += 2
            else:
                buf.append(ch)
                i += 1
        if buf:
            tokens.append("".join(buf))
    return tokens


def _split_op(raw: str) -> tuple[str, str]:
    if raw.startswith("!~"):
        return "nregex", raw[2:]
    if raw.startswith("~"):
        return "regex", raw[1:]
    if raw.startswith("!="):
        return "ne", raw[2:]
    if raw.startswith("!"):
        return "nlike", raw[1:]
    if raw.startswith("="):
        return "eq", raw[1:]
    return "like", raw


def parse_query(query: str) -> list[Clause]:
    if not query or not query.strip():
        return []
    clauses: list[Clause] = []
    for tok in tokenize(query):
        if not tok:
            continue
        if ":" in tok and not tok.startswith(":"):
            key, _, rest = tok.partition(":")
            key = key.strip().lower()
            if key not in FIELD_MAP:
                raise ValueError(f"unknown field: {key!r}")
            op, value = _split_op(rest)
        else:
            key, op, value = DEFAULT_FIELD, "like", tok
        if value == "":
            raise ValueError(f"empty value for field {key!r}")
        clauses.append(Clause(key, op, value))
    return clauses


def compile_clauses(clauses: Iterable[Clause]) -> tuple[str, list[str]]:
    where: list[str] = []
    params: list[str] = []
    for c in clauses:
        col = FIELD_MAP[c.field]
        if c.op == "like":
            where.append(f"{col} LIKE ?")
            params.append(f"%{c.value}%")
        elif c.op == "nlike":
            where.append(f"({col} IS NULL OR {col} NOT LIKE ?)")
            params.append(f"%{c.value}%")
        elif c.op == "eq":
            where.append(f"{col} = ?")
            params.append(c.value)
        elif c.op == "ne":
            where.append(f"({col} IS NULL OR {col} <> ?)")
            params.append(c.value)
        elif c.op == "regex":
            _validate_regex(c)
            where.append(f"{col} REGEXP ?")
            params.append(c.value)
        elif c.op == "nregex":
            _validate_regex(c)
            where.append(f"({col} IS NULL OR NOT ({col} REGEXP ?))")
            params.append(c.value)
        else:
            raise ValueError(f"unknown operator {c.op!r} for field {c.field!r}")
    return " AND ".join(where), params


def _validate_regex(clause: Clause) -> None:
    try:
        re.compile(clause.value)
    except re.error as e:
        raise ValueError(f"invalid regex for {clause.field!r}: {e}") from e


def build_query_sql(query: str | None) -> tuple[str, list[str]]:
    if not query:
        return "", []
    clauses = parse_query(query)
    if not clauses:
        return "", []
    return compile_clauses(clauses)
