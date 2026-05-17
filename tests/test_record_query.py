import pytest

from msgflow.common.record_query import (
    And,
    Clause,
    Not,
    Or,
    build_query_sql,
    compile_clauses,
    parse_query,
    tokenize,
)


def test_tokenize_handles_quotes_operators_and_escaped_literals():
    assert tokenize(r"body:'hello world' sender:alice\ bob body:a\|b") == [
        "body",
        ":",
        "hello world",
        "sender",
        ":",
        "alice bob",
        "body",
        ":",
        "a|b",
    ]


def test_parse_query_supports_default_field_and_term_operators():
    assert parse_query(r"hello status:=success code:!123 body:~'验证码\d+'") == And(
        (
            Clause("body", "like", "hello"),
            Clause("status", "eq", "success"),
            Clause("code", "nlike", "123"),
            Clause("body", "regex", r"验证码\d+"),
        )
    )


def test_parse_query_supports_or_not_and_parentheses():
    assert parse_query("kind:sms -(sender:bot | body:debug)") == And(
        (
            Clause("kind", "like", "sms"),
            Not(
                Or(
                    (
                        Clause("sender", "like", "bot"),
                        Clause("body", "like", "debug"),
                    )
                )
            ),
        )
    )


def test_parse_query_supports_field_scoped_groups():
    assert parse_query("kind:sms status:(failed | success)") == And(
        (
            Clause("kind", "like", "sms"),
            Or(
                (
                    Clause("status", "like", "failed"),
                    Clause("status", "like", "success"),
                )
            ),
        )
    )


def test_parse_query_supports_field_scoped_operator_values():
    assert parse_query("status:(=failed | !=success | !~debug)") == Or(
        (
            Clause("status", "eq", "failed"),
            Clause("status", "ne", "success"),
            Clause("status", "nregex", "debug"),
        )
    )


@pytest.mark.parametrize(
    "query, message",
    [
        pytest.param("unknown:value", "unknown field", id="未知字段"),
        pytest.param("text:value", "unknown field", id="不支持 text 字段"),
        pytest.param("body:", "empty value", id="空字段值"),
        pytest.param("body:(failed |)", "missing expression after OR", id="OR 后缺少表达式"),
        pytest.param("kind:sms (status:failed", "missing closing parenthesis", id="括号未闭合"),
        pytest.param("body:'hello", "unclosed ' quote", id="引号未闭合"),
    ],
)
def test_parse_query_rejects_invalid_clauses(query, message):
    with pytest.raises(ValueError, match=message):
        parse_query(query)


def test_parse_query_rejects_leading_colon():
    with pytest.raises(ValueError, match="unexpected token"):
        parse_query(":value")


def test_compile_clauses_builds_sql_and_params_for_all_ops():
    sql, params = compile_clauses(
        [
            Clause("body", "like", "abc"),
            Clause("sender", "nlike", "bot"),
            Clause("status", "ne", "failed"),
            Clause("code", "nregex", r"\d+"),
        ]
    )

    assert sql == (
        "(mr.body LIKE ?) AND ((mr.sender IS NULL OR mr.sender NOT LIKE ?)) AND "
        "((rr.status IS NULL OR rr.status <> ?)) AND ((rr.code IS NULL OR NOT (rr.code REGEXP ?)))"
    )
    assert params == ["%abc%", "%bot%", "failed", r"\d+"]


def test_build_query_sql_compiles_boolean_expression_with_params():
    sql, params = build_query_sql("kind:sms (status:failed | status:success) -sender:bot")

    assert sql == (
        "(mr.kind LIKE ?) AND ((rr.status LIKE ?) OR (rr.status LIKE ?)) AND "
        "((mr.sender IS NULL OR mr.sender NOT LIKE ?))"
    )
    assert params == ["%sms%", "%failed%", "%success%", "%bot%"]


def test_build_query_sql_compiles_group_not_with_inverse_ops():
    sql, params = build_query_sql("-(sender:bot | body:debug)")

    assert sql == (
        "((mr.sender IS NULL OR mr.sender NOT LIKE ?)) AND "
        "((mr.body IS NULL OR mr.body NOT LIKE ?))"
    )
    assert params == ["%bot%", "%debug%"]


def test_build_query_sql_supports_regex_with_quoted_or_escaped_backslash():
    assert build_query_sql(r"code:~\\d+")[1] == [r"\d+"]
    assert build_query_sql(r"code:~'\d+'")[1] == [r"\d+"]


def test_build_query_sql_returns_empty_for_blank_query():
    assert build_query_sql(None) == ("", [])
    assert build_query_sql("   ") == ("", [])


def test_build_query_sql_rejects_invalid_regex():
    with pytest.raises(ValueError, match="invalid regex"):
        build_query_sql("body:~[")
