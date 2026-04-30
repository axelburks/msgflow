import os, re, yaml, copy
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
from base import (
  LOCAL_CHANNELS,
  AVAILABLE_CHANNELS,
  REQ_CHANNELS,
  ALLOWED_MATCH_TPL_VARS,
  ALLOWED_COND_KEYS,
  deep_merge_dicts,
  collect_tpl_vars,
  render_value,
)
from defaults import CONFIG_DEFAULTS

cfg: Optional["Config"] = None

config_dir_default = '~/.config/msgflow'
config_dir_debug = f"{config_dir_default}/debug"
config_file = 'config.yaml'
record_file = 'record.json'

Strategy: TypeAlias = Literal["all", "until_success"]
CondKey: TypeAlias = Literal[ALLOWED_COND_KEYS]  # type: ignore
MatchKey: TypeAlias = Literal[ALLOWED_MATCH_TPL_VARS]  # type: ignore
Channel: TypeAlias = Literal[AVAILABLE_CHANNELS]  # type: ignore
LocalChannel: TypeAlias = Literal[LOCAL_CHANNELS]  # type: ignore
ReqChannel: TypeAlias = Literal[REQ_CHANNELS]  # type: ignore
CondValue: TypeAlias = Union[str, Dict[CondKey, str], StrictInt, Dict[CondKey, StrictInt]]

class _BaseCfgModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

class LocalPayloadModel(_BaseCfgModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    title: CondValue
    body: CondValue
    # 注意：pydantic.BaseModel 自带 copy/model_copy；字段名用 copy 会触发“shadows an attribute”警告，所以这里用 copy_ + alias="copy"
    copy_: Optional[CondValue] = Field(default=None, alias="copy")
    autoCopy: Optional[CondValue] = None

class BuiltDestinationBase(_BaseCfgModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    name_mark: str
    target: str
    channel: Channel
    logmarker: Optional[str] = '🎯'
    payload: Dict[str, Any]

    @model_validator(mode="after")
    def _validate_tpl_vars(self):
        dest = self.model_dump(by_alias=True, exclude_none=True)
        used = collect_tpl_vars(dest, key_name=None)
        unknown = sorted(v for v in used if v not in ALLOWED_MATCH_TPL_VARS)
        if unknown:
            raise ValueError(f"destination '{self.name_mark}' has unknown tpl vars: {unknown}")
        return self

class LocalDestinationModel(BuiltDestinationBase):
    channel: LocalChannel
    payload: LocalPayloadModel

class ReqDestinationModel(BuiltDestinationBase):
    channel: ReqChannel
    method: str
    url: CondValue
    params: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[Union[float, int, Tuple[Union[float, int], Union[float, int]]]] = None
    success_json: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _validate_request_preparable(self):
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

BuiltDestinationModel: TypeAlias = Annotated[
    Union[LocalDestinationModel, ReqDestinationModel],
    Field(discriminator="channel"),
]

class OriDestinationModel(_BaseCfgModel):
    target: str

class AndOrFilterModel(_BaseCfgModel):
    type: Literal["and", "or"]
    match: Dict[MatchKey, str]

    @model_validator(mode="after")
    def _validate_match_regex(self):
        for k, v in self.match.items():
            if not isinstance(v, str):
                raise ValueError(f"match[{k!r}] must be a regex string, got {type(v).__name__}")
            try:
                re.compile(v)
            except re.error as e:
                raise ValueError(f"match[{k!r}] is not a valid regex: {e}")
        return self

class SelectorFilterModel(_BaseCfgModel):
    type: Literal["selector"]
    match: Dict[MatchKey, StrictBool]

FilterModel: TypeAlias = Annotated[
    Union[AndOrFilterModel, SelectorFilterModel],
    Field(discriminator="type"),
]

DestT = TypeVar("DestT")

class ForwardRuleModel(_BaseCfgModel, Generic[DestT]):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    name_mark: str
    strategy: Optional[Strategy] = None
    filters: List[FilterModel] = Field(default_factory=list)
    destinations: List[DestT]

class ForwardModel(_BaseCfgModel, Generic[DestT]):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    strategy: Strategy
    rules: List[ForwardRuleModel[DestT]]

class AlarmModel(_BaseCfgModel, Generic[DestT]):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    strategy: Strategy
    destinations: List[DestT] = Field(default_factory=list)

class TargetModel(_BaseCfgModel):
    channel: Channel

class CfgModel(_BaseCfgModel, Generic[DestT]):
    check_interval: int = Field(ge=1)
    source: str
    target: Dict[str, TargetModel]
    forward: ForwardModel[DestT]
    alarm: AlarmModel[DestT]

EffectiveCfgModel: TypeAlias = CfgModel[OriDestinationModel]
BuiltCfgModel: TypeAlias = CfgModel[BuiltDestinationModel]


class Config:
    def __init__(self, debug: bool = False):
        self.default_cfg = copy.deepcopy(CONFIG_DEFAULTS)
        self.debug_mode = debug
    
    def _update_cfg(self, config_dir):
        self.config_file_path = os.path.expanduser(f"{config_dir}/{config_file}")
        self.record_file_path = os.path.expanduser(f"{config_dir}/{record_file}")
        with open(self.config_file_path, 'r') as fp:
            self.user_cfg = yaml.safe_load(fp) or {}
        self.effective_cfg = deep_merge_dicts(self.default_cfg, self.user_cfg)
        self._validate_effective_cfg()
        forward_rules = self._build_forward_rules()
        alarm_destinations = self._build_alarm_destinations()
        self.built_cfg = deep_merge_dicts(
            self.effective_cfg,
            {
                "forward": {"rules": forward_rules},
                "alarm": {"destinations": alarm_destinations},
            },
        )
        self._validate_built_cfg()

    @property
    def debug_mode(self):
        return self._debug_mode

    @debug_mode.setter
    def debug_mode(self, value):
        self._debug_mode = value
        if self._debug_mode:
            self._update_cfg(config_dir_debug)
        else:
            self._update_cfg(config_dir_default)

    def _resolve_destination(self, destination):
        target_name = destination['target']
        targets = self.effective_cfg['target']
        if target_name not in targets:
            raise ValueError(
                f"unknown target '{target_name}', available: {sorted(targets.keys())}"
            )
        user_target_cfg = targets[target_name]
        channel_name = user_target_cfg['channel']
        channel_cfg = self.effective_cfg['channel'].get(channel_name) or {}

        merged = deep_merge_dicts(channel_cfg, user_target_cfg)
        merged = deep_merge_dicts(merged, destination)
        merged['name_mark'] = destination.get('name_mark') or target_name
        return merged

    def _build_destinations(self, destinations, name_mark_prefix: str = ""):
        built = []
        name_marks = set()
        for idx, dest in enumerate(destinations):
            try:
                dest_merged = self._resolve_destination(dest)
            except Exception as e:
                raise Exception(f"destinations[{idx}]: {e}")
            name_mark = dest_merged['name_mark']
            if name_mark_prefix:
                name_mark = f"{name_mark_prefix}_{name_mark}"
                dest_merged["name_mark"] = name_mark
            if name_mark in name_marks:
                raise Exception(f"duplicate destination name_mark '{name_mark}'")
            name_marks.add(name_mark)
            built.append(dest_merged)
        return built

    def _build_forward_rules(self):
        fwd_opt = self.effective_cfg['forward']
        fwd_strategy = fwd_opt['strategy']
        rules = fwd_opt['rules']
        built_rules = []
        for rule in rules:
            rule_name_mark = rule['name_mark']
            filters = rule['filters']
            strategy = rule.get('strategy') or fwd_strategy
            destinations = rule['destinations']
            try:
                built_dests = self._build_destinations(destinations, name_mark_prefix=rule_name_mark)
            except Exception as e:
                raise Exception(f"build_forward_rules error: rule '{rule_name_mark}' destinations: {e}")

            built_rules.append(
                {
                    "name_mark": rule_name_mark,
                    "filters": filters,
                    "strategy": strategy,
                    "destinations": built_dests,
                }
            )
        return built_rules

    def _build_alarm_destinations(self):
        alarm_opt = self.effective_cfg['alarm']
        destinations = alarm_opt['destinations']
        try:
            return self._build_destinations(destinations)
        except Exception as e:
            raise Exception(f"build_alarm_destinations error: {e}")

    def _validate_effective_cfg(self):
        try:
            validated = EffectiveCfgModel.model_validate(self.effective_cfg)
            self.effective_cfg = validated.model_dump(by_alias=True)
        except Exception as e:
            if self._debug_mode:
                raise
            raise ValueError(f"invalid config: {e}") from None

    def _validate_built_cfg(self):
        try:
            validated = BuiltCfgModel.model_validate(self.built_cfg)
            self.built_cfg = validated.model_dump(by_alias=True)
        except Exception as e:
            if self._debug_mode:
                raise
            raise ValueError(f"invalid config: {e}") from None
