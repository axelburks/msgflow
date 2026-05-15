import copy, re, yaml
from typing import (
    Optional,
    Any,
    Dict,
    List,
    Tuple,
    Union,
    Literal,
    TypeAlias,
    TypeVar,
    Generic,
    Annotated,
)
import requests
from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    StrictBool,
    StrictInt,
    model_validator,
)
from ..service.channels import (
    LOCAL_CHANNELS,
    AVAILABLE_CHANNELS,
    REQ_CHANNELS,
)
from ..common.paths import config_root_dir, config_file_path, history_file_path
from ..common.templating import (
    ALLOWED_MATCH_TPL_VARS,
    ALLOWED_COND_KEYS,
    collect_tpl_vars,
    render_value,
)
from ..common.utils import deep_merge_dicts
from .defaults import CONFIG_DEFAULTS, CONFIG_TEMPLATE

# Global singleton populated by `app.main` once CLI args are parsed.
# Modules that need config access read `config.cfg` lazily to avoid import
# cycles with msgflow/channels.
cfg: Optional["Config"] = None

# Narrow type aliases used by the pydantic schema below. Using Literal[...] on
# tuples of allowed channel names lets pydantic produce precise error messages
# for unknown channels/conditions/templates.
Strategy: TypeAlias = Literal["all", "until_success"]
CondKey: TypeAlias = Literal[ALLOWED_COND_KEYS]  # type: ignore
MatchKey: TypeAlias = Literal[ALLOWED_MATCH_TPL_VARS]  # type: ignore
Channel: TypeAlias = Literal[AVAILABLE_CHANNELS]  # type: ignore
LocalChannel: TypeAlias = Literal[LOCAL_CHANNELS]  # type: ignore
ReqChannel: TypeAlias = Literal[REQ_CHANNELS]  # type: ignore
# A CondValue is either a plain value or a conditional mapping (e.g.
# {"$default": "...", "$code": "...", "$alarm": "..."}).
CondValue: TypeAlias = Union[str, Dict[CondKey, str], StrictInt, Dict[CondKey, StrictInt]]


class _BaseCfgModel(BaseModel):
    # Base model that allows extra fields (extra="allow") so users can add
    # non-validated keys without breaking validation. Stricter child models
    # override this with extra="forbid".
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class NotificationPayloadModel(_BaseCfgModel):
    """Payload schema for app-backed local notifications."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    title: CondValue
    body: CondValue
    # Note: pydantic.BaseModel already defines `copy` / `model_copy`; naming a
    # field `copy` triggers a "shadows an attribute" warning, so we use
    # `copy_` with alias="copy" to keep the config key human-friendly.
    copy_: Optional[CondValue] = Field(default=None, alias="copy")
    autoCopy: Optional[CondValue] = None


class FloatingPayloadModel(_BaseCfgModel):
    """Payload schema for app-backed floating panels."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    title: CondValue
    body: CondValue
    input: CondValue


class BuiltDestinationBase(_BaseCfgModel):
    """Shared fields for any fully-built destination (after defaults merge)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    name_mark: str
    target: str
    channel: Channel
    logmarker: Optional[str] = '🎯'
    payload: Dict[str, Any]
    sms: Optional[Dict[str, Any]] = None
    notify: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _validate_tpl_vars(self) -> "BuiltDestinationBase":
        # Walk the whole destination tree and make sure every {{var}} used in
        # templates is in the allowlist, catching typos at config load time.
        dest = self.model_dump(by_alias=True, exclude_none=True)
        used = collect_tpl_vars(dest, key_name=None)
        unknown = sorted(v for v in used if v not in ALLOWED_MATCH_TPL_VARS)
        if unknown:
            raise ValueError(f"destination '{self.name_mark}' has unknown tpl vars: {unknown}")
        return self


PayloadT = TypeVar("PayloadT")


class LocalKindOverrideModel(_BaseCfgModel, Generic[PayloadT]):
    """Kind-specific override block shared by app-backed local channels."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    payload: PayloadT


class LocalDestinationModel(BuiltDestinationBase, Generic[PayloadT]):
    """Shared destination shape for app-backed local channels."""

    payload: PayloadT
    sms: Optional[LocalKindOverrideModel[PayloadT]] = None
    notify: Optional[LocalKindOverrideModel[PayloadT]] = None


class NotificationDestinationModel(LocalDestinationModel[NotificationPayloadModel]):
    """Destination bound to the app-backed local notification channel."""

    channel: Literal["notification"]


class FloatingDestinationModel(LocalDestinationModel[FloatingPayloadModel]):
    """Destination bound to the app-backed floating panel channel."""

    channel: Literal["floating"]


class ReqDestinationModel(BuiltDestinationBase):
    """Destination bound to an HTTP-based channel (webhook/bark/tg/etc.)."""

    channel: ReqChannel
    method: str
    url: CondValue
    params: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[Union[float, int, Tuple[Union[float, int], Union[float, int]]]] = None
    success_json: Optional[Dict[str, Any]] = None
    sms: Optional[Dict[str, Any]] = None
    notify: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _validate_request_preparable(self) -> "ReqDestinationModel":
        # Try to render templates with an empty mapping and then prepare a
        # `requests.Request`. This surfaces invalid URLs/headers/params at
        # config-load time instead of at first delivery attempt.
        url = render_value(self.url, {}, has_code=False, is_alarm=False)
        params = render_value(self.params, {}, has_code=False, is_alarm=False)
        headers = render_value(self.headers, {}, has_code=False, is_alarm=False)
        payload = render_value(self.payload, {}, has_code=False, is_alarm=False)
        req = requests.Request(
            method=self.method,
            url=url,
            params=params,
            headers=headers,
            json=payload,
        )
        try:
            req.prepare()
        except Exception as e:
            raise ValueError(f"invalid http request params: {e}")
        return self


# A destination is one of the two concrete shapes above; the `channel` field
# acts as the pydantic discriminator so only the matching model runs.
BuiltDestinationModel: TypeAlias = Annotated[
    Union[NotificationDestinationModel, FloatingDestinationModel, ReqDestinationModel],
    Field(discriminator="channel"),
]


class OriDestinationModel(_BaseCfgModel):
    # Original (pre-merge) destination: user only references a target by name;
    # the rest is resolved from `target` + `channel` defaults.
    target: str


class AndOrFilterModel(_BaseCfgModel):
    type: Literal["and", "or"]
    match: Dict[MatchKey, str]

    @model_validator(mode="after")
    def _validate_match_regex(self) -> "AndOrFilterModel":
        # Validate each match value is a compilable regex string so we don't
        # wait until runtime to discover a syntax error.
        for k, v in self.match.items():
            if not isinstance(v, str):
                raise ValueError(f"match[{k!r}] must be a regex string, got {type(v).__name__}")
            try:
                re.compile(v)
            except re.error as e:
                raise ValueError(f"match[{k!r}] is not a valid regex: {e}")
        return self


class SelectorFilterModel(_BaseCfgModel):
    # Selector filter uses booleans (has / hasn't) instead of regex patterns.
    type: Literal["selector"]
    match: Dict[MatchKey, StrictBool]


FilterModel: TypeAlias = Annotated[
    Union[AndOrFilterModel, SelectorFilterModel],
    Field(discriminator="type"),
]

# Destinations are generic so the same rule/flow models can be validated both
# in the "original" (pre-build) and the "built" (post-merge) representation.
DestT = TypeVar("DestT")


class RuleModel(_BaseCfgModel, Generic[DestT]):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    name_mark: str
    strategy: Optional[Strategy] = None
    filters: List[FilterModel] = Field(default_factory=list)
    destinations: List[DestT]


class SMSModel(_BaseCfgModel, Generic[DestT]):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    strategy: Strategy
    rules: List[RuleModel[DestT]] = Field(default_factory=list)


class NotifyModel(_BaseCfgModel, Generic[DestT]):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    strategy: Strategy
    rules: List[RuleModel[DestT]] = Field(default_factory=list)


class AlarmModel(_BaseCfgModel, Generic[DestT]):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    strategy: Strategy
    destinations: List[DestT] = Field(default_factory=list)


class AppRetentionKindModel(_BaseCfgModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    mode: Literal["count", "days"]
    value: int = Field(ge=1)


class AppRetentionModel(_BaseCfgModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    sms: AppRetentionKindModel
    notify: AppRetentionKindModel


class AppModel(_BaseCfgModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    retention: AppRetentionModel


class TargetModel(_BaseCfgModel):
    channel: Channel


class CfgModel(_BaseCfgModel, Generic[DestT]):
    check_interval: int = Field(ge=1)
    source: str
    target: Dict[str, TargetModel]
    sms: SMSModel[DestT]
    notify: NotifyModel[DestT]
    alarm: AlarmModel[DestT]
    app: AppModel


# Two concrete config shapes:
#   - Effective: user-authored config merged with defaults (targets still by name).
#   - Built:    fully-resolved config with every destination expanded.
EffectiveCfgModel: TypeAlias = CfgModel[OriDestinationModel]
BuiltCfgModel: TypeAlias = CfgModel[BuiltDestinationModel]


class Config:
    """
    Load, merge and validate msgflow configuration.

    The lifecycle is:
      1) Load user YAML and deep-merge over package defaults -> `effective_cfg`.
      2) Validate the effective shape with pydantic.
      3) Build fully-resolved destinations (channel + target + destination
         overrides merged together) -> `built_cfg`.
      4) Validate the built shape with pydantic.
    """

    def __init__(self, debug: bool = False) -> None:
        self.default_cfg = copy.deepcopy(CONFIG_DEFAULTS)
        # Assigning via the setter triggers an immediate `_update_cfg` so the
        # object is fully usable right after construction.
        self.debug_mode = debug

    def _update_cfg(self, debug: bool) -> None:
        # Load YAML, merge with defaults and build the resolved destination tree.
        # Splitting this into a separate method (instead of doing it inline in
        # `__init__`) lets the `debug_mode` setter re-run it when toggled.
        self.config_root_dir = str(config_root_dir())
        self.config_file_path = str(config_file_path(debug))
        self.history_file_path = str(history_file_path(debug))
        self._ensure_config_files(debug)
        with open(self.config_file_path, 'r') as fp:
            self.user_cfg: Dict[str, Any] = yaml.safe_load(fp) or {}
        self.effective_cfg: Dict[str, Any] = deep_merge_dicts(self.default_cfg, self.user_cfg)
        self._validate_effective_cfg()
        alarm_destinations = self._build_alarm_destinations()
        built_overlay = {
            "alarm": {"destinations": alarm_destinations},
        }
        sms_rules = self._build_sms_rules()
        notify_rules = self._build_notify_rules()
        if sms_rules:
            built_overlay["sms"] = {"rules": sms_rules}
        if notify_rules:
            built_overlay["notify"] = {"rules": notify_rules}
        self.built_cfg: Dict[str, Any] = deep_merge_dicts(self.effective_cfg, built_overlay)
        self._validate_built_cfg()

    def _ensure_config_files(self, debug: bool) -> None:
        config_path = config_file_path(debug)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")

    @property
    def debug_mode(self) -> bool:
        return self._debug_mode

    @debug_mode.setter
    def debug_mode(self, value: bool) -> None:
        # Swapping debug mode also swaps the config directory, so we reload
        # everything to keep the object consistent with the new source path.
        self._debug_mode = value
        self._update_cfg(debug=self._debug_mode)

    def _resolve_destination(self, destination: Dict[str, Any], kind: Optional[str] = None) -> Dict[str, Any]:
        # Merge precedence (low -> high):
        #   channel defaults -> channel[kind] overlay -> user target cfg -> destination overrides
        # This lets channel-level/kind-level/target-level settings compose cleanly.
        target_name = destination['target']
        targets = self.effective_cfg['target']
        if target_name not in targets:
            raise ValueError(
                f"unknown target '{target_name}', available: {sorted(targets.keys())}"
            )
        user_target_cfg = targets[target_name]
        channel_name = user_target_cfg['channel']
        channel_cfg = self.effective_cfg['channel'].get(channel_name) or {}

        # Apply a per-kind overlay (e.g. channel.bark.notify) when the
        # destination is attached to a specific flow kind.
        if kind and isinstance(channel_cfg.get(kind), dict):
            channel_cfg = deep_merge_dicts(channel_cfg, channel_cfg[kind])

        merged = deep_merge_dicts(channel_cfg, user_target_cfg)
        merged = deep_merge_dicts(merged, destination)
        # Default the display name to the target name; per-destination
        # `name_mark` still wins when provided.
        merged['name_mark'] = destination.get('name_mark') or target_name
        return merged

    def _build_destinations(
        self,
        destinations: List[Dict[str, Any]],
        name_mark_prefix: str = "",
        kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        # Resolve every destination in a rule and ensure their final
        # `name_mark`s are unique (so cursor-state keys don't collide).
        built: List[Dict[str, Any]] = []
        name_marks: set[str] = set()
        for idx, dest in enumerate(destinations):
            try:
                dest_merged = self._resolve_destination(dest, kind=kind)
            except Exception as e:
                raise Exception(f"destinations[{idx}]: {e}")
            name_mark = dest_merged['name_mark']
            if name_mark_prefix:
                # Scope the name_mark under its rule/kind so the same target can
                # be reused safely in multiple rules with independent cursors.
                name_mark = f"{name_mark_prefix}_{name_mark}"
                dest_merged["name_mark"] = name_mark
            if name_mark in name_marks:
                raise Exception(f"duplicate destination name_mark '{name_mark}'")
            name_marks.add(name_mark)
            built.append(dest_merged)
        return built

    def _build_sms_rules(self) -> Optional[List[Dict[str, Any]]]:
        sms_cfg = self.effective_cfg.get('sms')
        if not sms_cfg.get('rules'):
            return None
        return self._build_rules_by_key('sms')

    def _build_notify_rules(self) -> Optional[List[Dict[str, Any]]]:
        notify_cfg = self.effective_cfg.get('notify')
        if not notify_cfg.get('rules'):
            return None
        return self._build_rules_by_key('notify')

    def _build_rules_by_key(self, key: str) -> List[Dict[str, Any]]:
        # Build a list of fully-resolved rules for a given flow kind (sms/notify).
        opt = self.effective_cfg.get(key)
        default_strategy = opt.get('strategy')
        rules = opt.get('rules') or []
        built_rules: List[Dict[str, Any]] = []
        for rule in rules:
            rule_name_mark = rule['name_mark']
            filters = rule.get('filters', [])
            # Rule-level strategy overrides the flow default when provided.
            strategy = rule.get('strategy') or default_strategy
            destinations = rule['destinations']
            try:
                built_dests = self._build_destinations(
                    destinations,
                    name_mark_prefix=f"{key}_{rule_name_mark}",
                    kind=key,
                )
            except Exception as e:
                raise Exception(f"build_{key}_rules error: rule '{rule_name_mark}' destinations: {e}")

            built_rules.append(
                {
                    "name_mark": rule_name_mark,
                    "filters": filters,
                    "strategy": strategy,
                    "destinations": built_dests,
                }
            )
        return built_rules

    def _build_alarm_destinations(self) -> List[Dict[str, Any]]:
        # Alarm destinations are not associated with a flow kind, so no prefix
        # is applied; they live in a single shared namespace.
        alarm_opt = self.effective_cfg['alarm']
        destinations = alarm_opt['destinations']
        try:
            return self._build_destinations(destinations)
        except Exception as e:
            raise Exception(f"build_alarm_destinations error: {e}")

    def _validate_effective_cfg(self) -> None:
        try:
            validated = EffectiveCfgModel.model_validate(self.effective_cfg)
            # Re-dump so downstream code sees normalized values (aliases
            # applied, defaults filled, etc.).
            self.effective_cfg = validated.model_dump(by_alias=True)
        except Exception as e:
            # Debug mode: re-raise the pydantic traceback for full detail.
            # Normal mode: wrap into a concise ValueError so CLI output stays clean.
            if self._debug_mode:
                raise
            raise ValueError(f"invalid config: {e}") from None

    def _validate_built_cfg(self) -> None:
        try:
            validated = BuiltCfgModel.model_validate(self.built_cfg)
            self.built_cfg = validated.model_dump(by_alias=True)
        except Exception as e:
            if self._debug_mode:
                raise
            raise ValueError(f"invalid config: {e}") from None
