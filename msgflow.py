import os, sys, time, json, random, traceback, logging
from typing import Any, Optional
import regex

from utils import format_ts, parse_time_str, get_code_from_text
from template import render_destination
from channels import Channels, CHANNEL_NOTIFIERS

logger = logging.getLogger(__name__)


class MsgFlow(Channels):
    """
    Base class for a message forwarding flow.

    Subclasses (e.g. SMSFlow, NotifyFlow) implement `query_new_msgs` to fetch
    new messages from a data source and reuse the shared pipeline provided
    here: filtering, rendering, dispatching to destinations, alarm handling
    and persistence of the last-forwarded timestamp per destination.
    """

    KIND = "msg"
    NEW_MSG_HIT = "new"
    DONE_MSG_HIT = "done"
    NO_NEW_MSG_TEXT = "no msg received for 24h"
    # Mock 数据文件路径；子类必须显式指定，供 `mock_to_forward` 读取。
    MOCK_FILE: Optional[str] = None

    def __init__(self) -> None:
        import config as _config
        super().__init__()
        self.is_1st_start = True
        self.update_time: dict[str, float] = {}
        self.built_cfg = _config.cfg.built_cfg
        self.rules = self.built_cfg.get(self.KIND, {}).get('rules', [])
        self.destinations = self._flatten_destinations()
        self.alarm_strategy = self.built_cfg['alarm']['strategy']
        self.alarm_destinations = self.built_cfg['alarm']['destinations']
        self.source = self.built_cfg.get('source')
        self.last_fwd_time_file = _config.cfg.record_file_path
        self.init_update_time()

    # ---------- Config / state ----------

    def _flatten_destinations(self) -> list[dict[str, Any]]:
        # Flatten destinations across all rules into a single list
        # so we can uniformly track last-forwarded time per destination.
        flat = []
        for rule in self.rules:
            flat.extend(rule['destinations'])
        return flat

    def init_update_time(self, load_saved: bool = True) -> None:
        # Initialize `update_time` (last-forwarded timestamp per destination).
        # When `load_saved` is True, previously persisted values are restored
        # so restarts don't re-forward old messages.
        saved_update_time = None
        if load_saved and os.path.exists(self.last_fwd_time_file):
            try:
                with open(self.last_fwd_time_file, 'r') as fp:
                    data = json.load(fp)
                if isinstance(data, dict):
                    saved_update_time = data.get(self.KIND)
            except Exception as e:
                logger.warning(f"reading last_fwd_time_file error: {e}")

        init_timestamp = time.time()
        for dest in self.destinations:
            dest_name = dest['name_mark']
            # Local-only channels (e.g. macOS notification) are not persisted:
            # they are side effects on the current machine, not remote delivery,
            # so always start from "now" to avoid spamming on restart.
            if dest.get('channel') == 'notification':
                self.update_time[dest_name] = init_timestamp
                continue
            if saved_update_time and dest_name in saved_update_time:
                saved_value = saved_update_time[dest_name]
                parsed = parse_time_str(saved_value)
                if parsed is None:
                    raise ValueError(
                        f"saved_update_time has invalid time format for '{dest_name}': {saved_value}"
                    )
                self.update_time[dest_name] = parsed
            else:
                self.update_time[dest_name] = init_timestamp
        self.min_update_time = min(self.update_time.values()) if self.update_time else init_timestamp
        self.last_new_msg_time = init_timestamp

    def write_last_fwd_time_to_file(self, mock: bool = False) -> None:
        # Persist last-forwarded timestamps atomically via write-tmp + os.replace
        # to avoid corrupting the JSON record if the process is killed mid-write.
        self.is_1st_start = False
        if mock:
            return
        existing = {}
        if os.path.exists(self.last_fwd_time_file):
            try:
                with open(self.last_fwd_time_file, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        existing = loaded
            except Exception:
                existing = {}
        existing[self.KIND] = {k: format_ts(v) for k, v in self.update_time.items()}
        tmp_file = self.last_fwd_time_file + '.tmp'
        with open(tmp_file, 'w') as f:
            json.dump(existing, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, self.last_fwd_time_file)

    # ---------- Filters / send ----------

    def is_filter_matched(self, msg: dict[str, Any], match: dict[str, Any], match_type: str) -> bool:
        # Evaluate a single filter clause against a message.
        # - "and": every key/regex in `match` must match the corresponding msg field
        # - "or":  any key/regex in `match` matches the corresponding msg field
        # - "selector": boolean "has/has-not" test for each key in `match`
        try:
            if match_type == 'and':
                return all(key in msg and regex.match(str(pattern), str(msg[key])) for key, pattern in match.items())
            elif match_type == 'or':
                return any(key in msg and regex.match(str(pattern), str(msg[key])) for key, pattern in match.items())
            elif match_type == 'selector':
                return all((bool(pattern) and bool(msg.get(key))) or ((not bool(pattern)) and (not msg.get(key))) for key, pattern in match.items())
        except Exception as e:
            logger.error(f"❌ filter error: {e}")
            return False

    def check_filters(self, msg: dict[str, Any], filters: Optional[list[dict[str, Any]]]) -> bool:
        # All configured filters must pass (logical AND between filters).
        if filters:
            for f in filters:
                if not self.is_filter_matched(msg, f['match'], f['type']):
                    logger.debug(f"🕸️  filter [x]: {json.dumps(f, ensure_ascii=False, default=str)}")
                    return False
                else:
                    logger.debug(f"🕸️  filter [√]: {json.dumps(f, ensure_ascii=False, default=str)}")
            return True
        logger.debug("🕸️  no filters")
        return True

    def _send_to_destination(self, dest: dict[str, Any]) -> tuple[bool, Any]:
        # Dispatch the (already rendered) destination to the right channel notifier.
        notify = CHANNEL_NOTIFIERS[dest["channel"]]
        return notify(self, dest)

    # ---------- Command entrypoints ----------

    def check_destinations(self) -> None:
        # Validate every destination is reachable by sending a synthetic "check passed"
        # message. Used by the `--check` CLI mode to fail fast on misconfigured channels.
        for dest in self.destinations:
            dest_name = dest.get('name_mark')
            dest_mark = f"{dest.get('logmarker')} {dest_name}({dest.get('channel')})"
            try:
                check_title = f"{dest_mark} check passed"
                check_msg = {"source": self.source}
                rendered_dest = render_destination(dest, check_msg, is_alarm=True, error=check_title)
                cur_status, cur_res = self._send_to_destination(rendered_dest)
                if not cur_status:
                    logger.error(f"❌ {dest_mark} error: {cur_res}")
                    sys.exit(1)
            except Exception as e:
                logger.error(f"❌ {dest_mark} error: {e}")
                sys.exit(1)

    def send_alarm(self, msg: Optional[dict[str, Any]] = None, **kwargs: Any) -> bool:
        # Fan out an alarm message to alarm destinations according to `alarm_strategy`.
        # - "until_success": stop at the first successful delivery
        # - "all":           deliver to all; success means no destination failed
        if msg is None:
            msg = {}
        logger.info(f"{'#' * 15} ⚠️  {self.KIND} alarm start {'#' * 15}")
        try:
            msg['source'] = self.source
            any_success = False
            any_failed = False
            for dest in self.alarm_destinations:
                rendered_dest = render_destination(dest, msg, is_alarm=True, **kwargs)
                cur_status, cur_res = self._send_to_destination(rendered_dest)
                if cur_status:
                    any_success = True
                    if self.alarm_strategy == 'until_success':
                        return True
                else:
                    any_failed = True
                    logger.error(f"❌ alarm failed: {cur_res}")
            if self.alarm_strategy == 'all':
                return not any_failed
            return any_success
        finally:
            logger.info(f"{'#' * 15} ⚠️  {self.KIND} alarm end {'#' * 15}")

    def forward_msg(self, msg: dict[str, Any]) -> bool:
        # Forward a single message through every configured rule.
        # For each rule, apply filters, then attempt delivery per destination
        # using the rule's strategy. Advance `update_time` per destination so
        # already-delivered (or filtered-out) messages are not retried.
        msg['source'] = self.source
        msg_ts = msg.get('timestamp')
        overall_ok = True
        for rule in self.rules:
            rule_name = rule.get('name_mark')
            rule_filters = rule.get('filters')
            rule_strategy = rule.get('strategy')
            rule_dests = rule.get('destinations')
            logger.info(f"📏 {rule_name}({rule_strategy})")

            if not self.check_filters(msg, rule_filters):
                # Filter failed: still advance per-destination cursors so this
                # message won't be re-evaluated on the next tick.
                for dest in rule_dests:
                    dest_name = dest["name_mark"]
                    if msg_ts > self.update_time.get(dest_name, 0):
                        self.update_time[dest_name] = msg_ts
                continue

            attempted = 0
            any_success = False
            any_failed = False
            errors = []

            for idx, dest in enumerate(rule_dests):
                dest_name = dest["name_mark"]
                dest_mark = f"{dest.get('logmarker')} {dest_name}({dest.get('channel')})"
                last_ts = self.update_time.get(dest_name, 0)
                ts_passed = msg_ts > last_ts
                logger.debug(
                    f"{dest_mark} ts "
                    f"{'[√]' if ts_passed else '[x]'}: "
                    f"{format_ts(msg_ts)} {'>' if ts_passed else '<='} {format_ts(last_ts)}"
                    f" ({msg_ts} {'>' if ts_passed else '<='} {last_ts})"
                )
                if not ts_passed:
                    # This destination has already been updated past msg_ts
                    # (e.g. delivered previously), skip.
                    continue

                rendered_dest = render_destination(dest, msg, is_alarm=False)
                cur_status, cur_res = self._send_to_destination(rendered_dest)

                attempted += 1
                if cur_status:
                    any_success = True
                    self.update_time[dest_name] = msg_ts
                    if rule_strategy == "until_success":
                        # Short-circuit: mark remaining destinations as caught up
                        # to avoid re-sending this msg to them later.
                        for remaining in rule_dests[idx + 1:]:
                            r_name = remaining["name_mark"]
                            if msg_ts > self.update_time.get(r_name, 0):
                                self.update_time[r_name] = msg_ts
                        break
                else:
                    any_failed = True
                    logger.error(f"❌ forward_{self.KIND} failed: {cur_res}")
                    errors.append(f"{cur_res}")

            if rule_strategy == "all":
                # "all": raise alarm if any destination in the rule failed.
                if attempted > 0 and any_failed:
                    overall_ok = False
                    self.send_alarm(
                        msg,
                        error=f"({rule_strategy}) some destinations failed",
                        traceback="\n\n".join(errors) if errors else None,
                    )
            else:
                # "until_success": raise alarm only if every destination failed.
                if attempted > 0 and (not any_success):
                    overall_ok = False
                    self.send_alarm(
                        msg,
                        error=f"({rule_strategy}) all destinations failed",
                        traceback="\n\n".join(errors) if errors else None,
                    )
        return overall_ok

    # ---------- Main loop entrypoint ----------

    def query_new_msgs(self) -> list[dict[str, Any]]:
        # Subclasses must return a list of new-message dicts sorted by timestamp,
        # containing at minimum a `timestamp` field (float seconds since epoch).
        raise NotImplementedError

    def mock_to_forward(self, num: int) -> None:
        # Mock mode: replay random samples from MOCK_FILE as if they just
        # arrived. Used to validate rules/templates/destinations without
        # real traffic.
        if not self.MOCK_FILE:
            raise ValueError(f"{type(self).__name__} did not set MOCK_FILE")
        mock_file = os.path.expanduser(self.MOCK_FILE)
        with open(mock_file, 'r') as f:
            msgs_list = json.load(f)
        if not isinstance(msgs_list, list):
            raise ValueError(f"invalid mock file format ({mock_file}), expected list, got {type(msgs_list)}")
        actual_num = min(len(msgs_list), num)
        new_msgs = random.sample(msgs_list, actual_num)
        # Reset cursors from "now" (ignore saved record) so all mock msgs pass
        # the timestamp gate.
        self.init_update_time(load_saved=False)

        for idx, msg in enumerate(new_msgs):
            msg["timestamp"] = self.min_update_time + idx + 1
            msg["time_str"] = format_ts(msg["timestamp"])

        try:
            self.send_alarm(error=f"mock starting ({self.KIND})")
            self.check_to_forward(mock=True, mock_msgs=new_msgs)
        except Exception as e:
            traceback.print_exc()
            self.send_alarm(error=str(e), traceback=traceback.format_exc())

    def check_to_forward(self, mock: bool = False, mock_msgs: list[dict[str, Any]] = []) -> None:
        # One tick of the main loop: fetch new messages and forward each of them.
        # Also handles the "no new message for 24h" watchdog and periodic cursor
        # advance when idle so the saved record stays fresh.
        self.min_update_time = min(self.update_time.values()) if self.update_time else time.time()
        logger.debug(f"[{self.KIND}] update_time: { {k: f'{format_ts(v)}({v})' for k, v in self.update_time.items()} }")
        logger.debug(f"[{self.KIND}] min_update_time: {format_ts(self.min_update_time)}({self.min_update_time})")
        c_timestamp = time.time()

        new_msgs = mock_msgs if mock else self.query_new_msgs()

        if new_msgs:
            self.last_new_msg_time = c_timestamp
            for msg in new_msgs:
                try:
                    print("")
                    logger.info(f"{'>' * 15} {self.NEW_MSG_HIT} {self.KIND} {'<' * 15}")
                    msg['time_str'] = format_ts(msg.get('timestamp', 0))
                    logger.info(f"📨 {json.dumps(msg, ensure_ascii=False, default=str)}")
                    # Keep a full JSON dump of the original message in `msg` so
                    # templates can reference the raw payload via {{msg}}.
                    msg['msg'] = json.dumps(msg, ensure_ascii=False, default=str)
                    msg['code'] = get_code_from_text(msg.get('text'))
                    if msg['code']:
                        logger.info(f"🔐 {msg['code']}")
                    self.forward_msg(msg)
                except Exception as e:
                    traceback.print_exc()
                    self.send_alarm(msg=msg, error=str(e), traceback=traceback.format_exc())
                    continue
                finally:
                    logger.info(f"{'>' * 15} {self.DONE_MSG_HIT} {self.KIND} {'<' * 15}")

            self.write_last_fwd_time_to_file(mock)

        elif c_timestamp - self.min_update_time > 60 * 10:
            # Idle > 10min: pull all destination cursors forward to "now" and
            # persist. This bounds the lookback window after long idles.
            self.update_time = {key: c_timestamp for key in self.update_time}
            self.write_last_fwd_time_to_file(mock)

        elif self.is_1st_start:
            # On the very first tick, persist the initial state so a fresh run
            # leaves a record file on disk even if no new message arrived.
            self.write_last_fwd_time_to_file(mock)

        if c_timestamp - self.last_new_msg_time > 60 * 60 * 24:
            # Watchdog: if no new message for 24h, surface it via a local
            # notification + alarm channels, then reset the watchdog timer.
            self.send_notification(self.NO_NEW_MSG_TEXT)
            self.send_alarm(error=self.NO_NEW_MSG_TEXT)
            self.last_new_msg_time = c_timestamp
    
    def update_hook(self) -> None:
        # Entry point invoked by the app scheduler on every tick.
        # Wraps `check_to_forward` so any unhandled error raises an alarm
        # instead of killing the main loop.
        try:
            self.check_to_forward()
        except Exception as e:
            traceback.print_exc()
            self.send_alarm(error=str(e), traceback=traceback.format_exc())
