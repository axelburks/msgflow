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
    field_validator,
    model_validator,
)
from ..common.run_models import MESSAGE_KINDS
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
HistoryMode: TypeAlias = Literal["from_now", "replay"]
CondKey: TypeAlias = Literal[ALLOWED_COND_KEYS]  # type: ignore
MatchKey: TypeAlias = Literal[ALLOWED_MATCH_TPL_VARS]  # type: ignore
Channel: TypeAlias = Literal[AVAILABLE_CHANNELS]  # type: ignore
LocalChannel: TypeAlias = Literal[LOCAL_CHANNELS]  # type: ignore
ReqChannel: TypeAlias = Literal[REQ_CHANNELS]  # type: ignore
CondValue: TypeAlias = Union[str, Dict[CondKey, str], StrictInt, Dict[CondKey, StrictInt]]
BUILT_KINDS = (*MESSAGE_KINDS, "alarm")


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


class FieldRewriteRuleModel(_BaseCfgModel):
    """A single regex rewrite rule, applied to one template-context field."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    pattern: str
    replace: str

    @field_validator("pattern")
    @classmethod
    def _pattern_compilable(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as e:
            raise ValueError(f"invalid regex pattern: {e}")
        return value


# field_rewrite is a dict keyed by ALLOWED_MATCH_TPL_VARS field names; each
# value is a list of rewrite rules applied in order. Single-dict shorthand is
# NOT supported per spec.
FieldRewriteModel: TypeAlias = Dict[MatchKey, List[FieldRewriteRuleModel]]


class BuiltDestinationBase(_BaseCfgModel):
    """Shared fields for any fully-built destination (after defaults merge)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    name_mark: str
    target: str
    channel: Channel
    logmarker: Optional[str] = "🎯"
    payload: Union[Dict[str, Any], str]
    field_rewrite: Optional[FieldRewriteModel] = Field(default_factory=dict)

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

    @model_validator(mode="after")
    def _validate_request_preparable(self) -> "ReqDestinationModel":
        # Try to render templates with an empty mapping and then prepare a
        # `requests.Request`. This surfaces invalid URLs/headers/params at
        # config-load time instead of at first delivery attempt.
        url = render_value(self.url, {}, has_code=False)
        params = render_value(self.params, {}, has_code=False)
        headers = render_value(self.headers, {}, has_code=False)
        payload = render_value(self.payload, {}, has_code=False)
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
KindRuntimeT = TypeVar("KindRuntimeT")


class RuleModel(_BaseCfgModel, Generic[DestT]):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    name_mark: str
    strategy: Optional[Strategy] = None
    filters: List[FilterModel] = Field(default_factory=list)
    destinations: List[DestT]


class _KindCfgModel(_BaseCfgModel, Generic[DestT, KindRuntimeT]):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    # Kind-level runtime is a partial overlay before build and a fully-resolved
    # RuntimeModel after build, so requiredness is enforced only by BuiltCfgModel.
    runtime: Optional[KindRuntimeT] = Field(default_factory=dict)
    rules: List[RuleModel[DestT]] = Field(default_factory=list)


class SMSModel(_KindCfgModel[DestT, KindRuntimeT], Generic[DestT, KindRuntimeT]):
    pass


class NotifyModel(_KindCfgModel[DestT, KindRuntimeT], Generic[DestT, KindRuntimeT]):
    pass


class IPNModel(_KindCfgModel[DestT, KindRuntimeT], Generic[DestT, KindRuntimeT]):
    pass


class AlarmModel(_KindCfgModel[DestT, KindRuntimeT], Generic[DestT, KindRuntimeT]):
    pass


class CodePatternRuleModel(_BaseCfgModel):
    """A single user-defined verification-code regex rule."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    pattern: str
    # Group selector: int index, named group string, or omitted to take the
    # whole match (group 0). Inline regex flags like `(?i)` / `(?m)` / `(?s)`
    # belong inside the pattern itself — no separate `flags` field is needed.
    group: Optional[Union[StrictInt, str]] = None

    @field_validator("pattern")
    @classmethod
    def _pattern_compilable(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as e:
            raise ValueError(f"invalid regex pattern: {e}")
        return value


class CodePatternModel(_BaseCfgModel):
    """User-defined verification-code extraction strategy."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    fallback_to_builtin: StrictBool = False
    rules: List[CodePatternRuleModel] = Field(default_factory=list)


class RetentionModel(_BaseCfgModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    mode: Literal["count", "days"]
    value: int = Field(ge=1)


class RuntimeModel(_BaseCfgModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    check_interval: int = Field(ge=1)
    retention: RetentionModel
    strategy: Strategy
    history_mode: HistoryMode
    stale_alarm_seconds: int = Field(ge=0)
    code_pattern: Optional[CodePatternModel] = None


class TargetModel(_BaseCfgModel):
    channel: Channel


class CfgModel(_BaseCfgModel, Generic[DestT, KindRuntimeT]):
    source: str
    runtime: RuntimeModel
    target: Dict[str, TargetModel] = Field(default_factory=dict)
    sms: SMSModel[DestT, KindRuntimeT] = Field(default_factory=SMSModel)
    notify: NotifyModel[DestT, KindRuntimeT] = Field(default_factory=NotifyModel)
    ipn: IPNModel[DestT, KindRuntimeT] = Field(default_factory=IPNModel)
    alarm: AlarmModel[DestT, KindRuntimeT] = Field(default_factory=AlarmModel)


# Two concrete config shapes:
#   - Effective: user-authored config merged with defaults (targets still by name).
#   - Built:    fully-resolved config with every destination expanded.
class EffectiveCfgModel(CfgModel[OriDestinationModel, Dict[str, Any]]):
    pass


class BuiltCfgModel(CfgModel[BuiltDestinationModel, RuntimeModel]):
    pass


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
        # Rebuild the entire config pipeline whenever the source path changes.
        self.config_root_dir = str(config_root_dir())
        self.config_file_path = str(config_file_path(debug))
        self.history_file_path = str(history_file_path(debug))
        self._ensure_config_files(debug)
        self.user_cfg = self._load_user_cfg()
        self.effective_cfg = self._build_effective_cfg()
        self._validate_effective_cfg()
        self.built_cfg = self._build_built_cfg()
        self._validate_built_cfg()

    def _load_user_cfg(self) -> Dict[str, Any]:
        with open(self.config_file_path, 'r', encoding="utf-8") as fp:
            return yaml.safe_load(fp) or {}

    def _build_effective_cfg(self) -> Dict[str, Any]:
        return deep_merge_dicts(self.default_cfg, self.user_cfg)

    def _build_kind_runtime(self, kind: str) -> Dict[str, Any]:
        return deep_merge_dicts(
            {"runtime": self.effective_cfg["runtime"]},
            self.effective_cfg[kind],
        )

    def _build_kind_cfg(self, kind: str) -> Dict[str, Any]:
        built_kind_cfg = self._build_kind_runtime(kind)
        built_kind_cfg["rules"] = self._build_rules_by_kind(kind, built_kind_cfg)
        return built_kind_cfg

    def _build_built_cfg(self) -> Dict[str, Any]:
        built_overlay = {
            kind: self._build_kind_cfg(kind)
            for kind in BUILT_KINDS
        }
        return deep_merge_dicts(self.effective_cfg, built_overlay)

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

    def _resolve_destination(
        self,
        destination: Dict[str, Any],
        kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Merge precedence (low -> high):
        #   channel defaults -> channel.kinds[kind] overlay -> user target cfg -> destination overrides
        # This lets channel-level/kind-level/target-level settings compose cleanly.
        target_name = destination["target"]
        targets = self.effective_cfg["target"]
        if target_name not in targets:
            raise ValueError(
                f"unknown target '{target_name}', available: {sorted(targets.keys())}"
            )
        user_target_cfg = targets[target_name]
        channel_name = user_target_cfg["channel"]
        channel_cfg = self.effective_cfg["channel"].get(channel_name) or {}
        kinds = channel_cfg.get("kinds") if isinstance(channel_cfg.get("kinds"), dict) else {}
        channel_base = {
            key: value
            for key, value in channel_cfg.items()
            if key != "kinds"
        }

        # Apply a per-kind overlay (e.g. channel.bark.notify) when the
        # destination is attached to a specific flow kind.
        if kind and isinstance(kinds.get(kind), dict):
            channel_base = deep_merge_dicts(channel_base, kinds[kind])

        merged = deep_merge_dicts(channel_base, user_target_cfg)
        merged = deep_merge_dicts(merged, destination)
        merged.pop("kinds", None)
        # Default the display name to the target name; per-destination
        # `name_mark` still wins when provided.
        merged["name_mark"] = destination.get("name_mark") or target_name
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
                raise ValueError(f"destinations[{idx}]: {e}")
            name_mark = dest_merged["name_mark"]
            if name_mark_prefix:
                # Scope the name_mark under its rule/kind so the same target can
                # be reused safely in multiple rules with independent cursors.
                name_mark = f"{name_mark_prefix}_{name_mark}"
                dest_merged["name_mark"] = name_mark
            if name_mark in name_marks:
                raise ValueError(f"duplicate destination name_mark '{name_mark}'")
            name_marks.add(name_mark)
            built.append(dest_merged)
        return built

    def _build_rules_by_kind(self, kind: str, built_kind_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Build a list of fully-resolved rules for a given flow kind.
        default_strategy = built_kind_cfg["runtime"]["strategy"]
        rules = built_kind_cfg["rules"]
        built_rules: List[Dict[str, Any]] = []
        for rule in rules:
            rule_name_mark = rule["name_mark"]
            filters = rule.get("filters", [])
            # `strategy` stays optional; flow code resolves the inheritance
            # chain (rule -> kind.runtime) at use-site, same as alarm_rules.
            strategy = rule.get("strategy") or default_strategy
            destinations = rule["destinations"]
            try:
                built_dests = self._build_destinations(
                    destinations,
                    name_mark_prefix=f"{kind}_{rule_name_mark}",
                    kind=kind,
                )
            except Exception as e:
                raise ValueError(f"build_{kind}_rules error: rule '{rule_name_mark}' destinations: {e}")

            built_rules.append(
                {
                    "name_mark": rule_name_mark,
                    "filters": filters,
                    "strategy": strategy,
                    "destinations": built_dests,
                }
            )
        return built_rules

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
