from typing import Any

from ..common.run_models import RunTriggerType
from .runtime import CoreRuntime


def _load_message_record(runtime: CoreRuntime, message_id: int) -> dict[str, Any]:
    message_detail = runtime.get_message_detail(message_id)
    if message_detail is None:
        raise ValueError(f"message '{message_id}' not found")
    message_record = message_detail["message"]
    message_payload = message_record.get("msg")
    if not isinstance(message_payload, dict):
        raise ValueError(f"message '{message_id}' has invalid payload")
    return message_record


def rematch_and_send(runtime: CoreRuntime, message_id: int) -> dict[str, Any]:
    message_record = _load_message_record(runtime, message_id)
    flow = runtime.get_flow_by_kind(message_record["kind"])
    return flow.process_message(
        message_record["msg"],
        trigger_type=RunTriggerType.REMATCH.value,
        message_id=message_id,
        persist_message=False,
        advance_cursor=False,
        enable_alarm=False,
    )


def resend_destination(
    runtime: CoreRuntime,
    message_id: int,
    rule_name: str,
    dest_name: str,
) -> dict[str, Any]:
    message_record = _load_message_record(runtime, message_id)
    flow = runtime.get_flow_by_kind(message_record["kind"])
    return flow.process_message(
        message_record["msg"],
        trigger_type=RunTriggerType.RESEND.value,
        message_id=message_id,
        selected_rule=rule_name,
        selected_dest=dest_name,
        persist_message=False,
        advance_cursor=False,
        enable_alarm=False,
    )
