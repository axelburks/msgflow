import pytest

from msgflow.common.record_query import (
    Clause,
    build_query_sql,
    compile_clauses,
    parse_query,
    tokenize,
)


def test_tokenize_handles_quotes_and_escaped_spaces():
    assert tokenize(r"text:'hello world' sender:alice\ bob plain") == [
        "text:hello world",
        "sender:alice bob",
        "plain",
    ]


def test_parse_query_supports_default_field_and_operators():
    assert parse_query("hello status:=success code:!123 text:~验证码") == [
        Clause("text", "like", "hello"),
        Clause("status", "eq", "success"),
        Clause("code", "nlike", "123"),
        Clause("text", "regex", "验证码"),
    ]


@pytest.mark.parametrize(
    "query, message",
    [
        pytest.param("unknown:value", "unknown field", id="未知字段"),
        pytest.param("text:", "empty value", id="空字段值"),
    ],
)
def test_parse_query_rejects_invalid_clauses(query, message):
    with pytest.raises(ValueError, match=message):
        parse_query(query)


def test_parse_query_treats_leading_colon_as_default_text():
    assert parse_query(":value") == [Clause("text", "like", ":value")]


def test_compile_clauses_builds_sql_and_params_for_all_ops():
    sql, params = compile_clauses(
        [
            Clause("text", "like", "abc"),
            Clause("sender", "nlike", "bot"),
            Clause("status", "ne", "failed"),
            Clause("code", "nregex", r"\d+"),
        ]
    )

    assert sql == (
        "mr.text LIKE ? AND (mr.sender IS NULL OR mr.sender NOT LIKE ?) AND "
        "(rr.status IS NULL OR rr.status <> ?) AND (rr.code IS NULL OR NOT (rr.code REGEXP ?))"
    )
    assert params == ["%abc%", "%bot%", "failed", r"\d+"]


def test_build_query_sql_returns_empty_for_blank_query():
    assert build_query_sql(None) == ("", [])
    assert build_query_sql("   ") == ("", [])


def test_build_query_sql_rejects_invalid_regex():
    with pytest.raises(ValueError, match="invalid regex"):
        build_query_sql("text:~[")
