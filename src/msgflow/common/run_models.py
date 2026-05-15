from dataclasses import dataclass
from enum import Enum


class MessageKind(str, Enum):
    SMS = "sms"
    NOTIFY = "notify"


class RunTriggerType(str, Enum):
    AUTO = "auto"
    REMATCH = "rematch"
    RESEND = "resend"


class RunStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


MESSAGE_KINDS = tuple(kind.value for kind in MessageKind)
RUN_TRIGGER_TYPES = tuple(trigger.value for trigger in RunTriggerType)
RUN_STATUSES = tuple(status.value for status in RunStatus)


@dataclass(frozen=True)
class RunQueryFilters:
    limit: int = 50
    offset: int = 0
    kind: str | None = None
    trigger_type: str | None = None
    status: str | None = None
    query: str | None = None
