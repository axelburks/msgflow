from msgflow.common.run_models import RunTriggerType
from msgflow.service.replay import rematch_and_send, resend_destination


class FakeFlow:
    def __init__(self):
        self.calls = []

    def process_message(self, message, **kwargs):
        self.calls.append((message, kwargs))
        return {"status": "success"}


class FakeRuntime:
    def __init__(self, detail):
        self.detail = detail
        self.flow = FakeFlow()

    def get_message_detail(self, message_id):
        assert message_id == 10
        return self.detail

    def get_flow_by_kind(self, kind):
        assert kind == "sms"
        return self.flow


def test_rematch_and_send_reprocesses_without_persisting_or_advancing_cursor():
    runtime = FakeRuntime(
        {
            "message": {
                "kind": "sms",
                "sender": "alice",
                "receiver": "bob",
                "ROWID": 1,
                "rowid": 1,
                "text": "hello",
                "body": "hello",
                "time_str": "2026-01-01 00:00:00",
                "timestamp": 1000,
                "msg": {"ROWID": 1, "text": "hello"},
            }
        }
    )

    result = rematch_and_send(runtime, 10)

    assert result == {"status": "success"}
    assert runtime.flow.calls == [
        (
            {
                "kind": "sms",
                "sender": "alice",
                "receiver": "bob",
                "ROWID": 1,
                "rowid": 1,
                "text": "hello",
                "body": "hello",
                "time_str": "2026-01-01 00:00:00",
                "timestamp": 1000,
                "msg": {"ROWID": 1, "text": "hello"},
            },
            {
                "trigger_type": RunTriggerType.REMATCH.value,
                "message_id": 10,
                "persist_message": False,
                "advance_cursor": False,
                "enable_alarm": False,
            },
        )
    ]


def test_resend_destination_targets_single_rule_and_destination():
    runtime = FakeRuntime({"message": {"kind": "sms", "body": "hello", "msg": {"ROWID": 1, "text": "hello"}}})

    result = resend_destination(runtime, 10, "code_rule", "bark_dest")

    assert result == {"status": "success"}
    assert runtime.flow.calls[0][1] == {
        "trigger_type": RunTriggerType.RESEND.value,
        "message_id": 10,
        "selected_rule": "code_rule",
        "selected_dest": "bark_dest",
        "persist_message": False,
        "advance_cursor": False,
        "enable_alarm": False,
    }
