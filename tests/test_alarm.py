from types import MethodType

from msgflow.service.flows.base import MsgFlow


def test_send_alarm_uses_rules_filters_and_kind_alarm_payload():
    flow = object.__new__(MsgFlow)
    flow.KIND = "sms"
    flow.source = "test-source"
    flow.alarm_strategy = "until_success"
    flow.alarm_rules = [
        {
            "name_mark": "ignored",
            "strategy": "until_success",
            "filters": [{"type": "and", "match": {"body": "network"}}],
            "destinations": [{"name_mark": "ignored", "channel": "webhook", "payload": {"title": "ignored"}}],
        },
        {
            "name_mark": "matched",
            "strategy": "until_success",
            "filters": [{"type": "selector", "match": {"body": True}}],
            "destinations": [
                {
                    "name_mark": "alarm_dest",
                    "channel": "webhook",
                    "payload": {"title": "{{source}}: {{error}}", "body": "{{trans}}\n{{text}}"},
                }
            ],
        },
    ]
    sent = []

    def fake_send_to_destination(self, dest):
        sent.append(dest)
        return True, "ok"

    flow._send_to_destination = MethodType(fake_send_to_destination, flow)

    assert MsgFlow.send_alarm(
        flow,
        msg={"sender": "core", "receiver": "ops", "title": "alarm", "body": "boom"},
        error="boom",
    ) is True
    assert [dest["name_mark"] for dest in sent] == ["alarm_dest"]
    assert sent[0]["payload"]["title"] == "test-source: boom"
    assert sent[0]["payload"]["body"] == "core <- ops\nalarm\nboom"
