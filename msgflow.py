import os, sys, time, json, random, traceback, logging
from typing import Any, Optional
import regex

from utils import format_ts, get_code_from_text
from template import render_destination
from channels import Channels, CHANNEL_NOTIFIERS

logger = logging.getLogger(__name__)


class MsgFlow(Channels):
    """
    Base class for a message forwarding flow.

    Subclasses (e.g. SMSFlow, NotifyFlow) implement `query_new_msgs` to fetch
    new messages from a data source and reuse the shared pipeline provided
    here: filtering, rendering, dispatching to destinations, alarm handling
    and persistence of the last-forwarded cursor per destination.

    The cursor is a monotonically increasing integer key local to each source
    DB (e.g. `message.ROWID` for chat.db, `record.rec_id` for usernoted.db),
    not a wall-clock timestamp. This is robust against records whose
    `date/delivered_date` is older than previously-seen rows (e.g. SMS that
    synced late from a flaky iPhone network).
    """

    KIND = "msg"
    NEW_MSG_HIT = "new"
    DONE_MSG_HIT = "done"
    NO_NEW_MSG_TEXT = "no msg received for 24h"
    # Cursor field name; subclasses must set this explicitly (for example,
    # "rowid" or "rec_id"). It is both the key in the `msg` dict and the
    # column alias selected in SQL.
    CURSOR_FIELD: Optional[str] = None
    # Path to the mock data file; subclasses must set this explicitly for
    # `mock_to_forward` to read.
    MOCK_FILE: Optional[str] = None

    def __init__(self) -> None:
        import config as _config
        super().__init__()
        if not self.CURSOR_FIELD:
            raise ValueError(f"{type(self).__name__} did not set CURSOR_FIELD")
        self.is_1st_start = True
        # Persisted: per-destination last-forwarded cursor key. The cursor is
        # monotonically increasing within a given flow (e.g. ROWID for SMS,
        # delivered_date for notifications) but its concrete type is chosen
        # by the subclass — int or float both work as long as `>` orders them
        # correctly and JSON round-trips losslessly.
        self.cursor: dict[str, float] = {}
        # In-memory only: last seen message timestamp per dest, for readable logs.
        self.last_seen_ts: dict[str, float] = {}
        self.built_cfg = _config.cfg.built_cfg
        self.rules = self.built_cfg.get(self.KIND, {}).get('rules', [])
        self.destinations = self._flatten_destinations()
        self.alarm_strategy = self.built_cfg['alarm']['strategy']
        self.alarm_destinations = self.built_cfg['alarm']['destinations']
        self.source = self.built_cfg.get('source')
        self.record_file = _config.cfg.record_file_path
        self.init_cursor()

    # ---------- Config / state ----------

    def _flatten_destinations(self) -> list[dict[str, Any]]:
        # Flatten destinations across all rules into a single list
        # so we can uniformly track last-forwarded cursor per destination.
        flat = []
        for rule in self.rules:
            flat.extend(rule['destinations'])
        return flat

    def initial_cursor(self) -> float:
        # Subclasses return the current max cursor key in the source DB,
        # used to initialize fresh destinations so they start "at DB tail"
        # rather than replaying history.
        raise NotImplementedError

    def init_cursor(self, load_saved: bool = True) -> None:
        # Initialize `cursor` (last-forwarded cursor key per destination).
        # When `load_saved` is True, previously persisted values are restored
        # so restarts don't re-forward old messages.
        saved_cursor = None
        if load_saved and os.path.exists(self.record_file):
            try:
                with open(self.record_file, 'r') as fp:
                    data = json.load(fp)
                if isinstance(data, dict):
                    saved_cursor = data.get(self.KIND)
            except Exception as e:
                logger.error(f"❌ reading record_file error: {e}")
                sys.exit(1)

        db_tail = self.initial_cursor()
        for dest in self.destinations:
            dest_name = dest['name_mark']
            # Local-only channels (e.g. macOS notification) are not persisted:
            # they are side effects on the current machine, not remote delivery,
            # so always start from the DB tail to avoid spamming on restart.
            if dest.get('channel') == 'notification':
                self.cursor[dest_name] = db_tail
                continue
            if saved_cursor and dest_name in saved_cursor:
                saved_value = saved_cursor[dest_name]
                if not isinstance(saved_value, (int, float)) or isinstance(saved_value, bool):
                    raise ValueError(
                        f"saved cursor has invalid type for '{dest_name}': {saved_value!r}"
                    )
                self.cursor[dest_name] = saved_value
            else:
                self.cursor[dest_name] = db_tail
        self.min_cursor = min(self.cursor.values()) if self.cursor else db_tail
        self.last_new_msg_time = time.time()

    def write_record_to_file(self, mock: bool = False) -> None:
        # Persist cursor values atomically via write-tmp + os.replace to
        # avoid corrupting the JSON record if the process is killed mid-write.
        self.is_1st_start = False
        if mock:
            return
        existing = {}
        if os.path.exists(self.record_file):
            try:
                with open(self.record_file, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        existing = loaded
            except Exception:
                existing = {}
        existing[self.KIND] = dict(self.cursor)
        tmp_file = self.record_file + '.tmp'
        with open(tmp_file, 'w') as f:
            json.dump(existing, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, self.record_file)

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

    def _advance_cursor(self, dest_name: str, msg_key: float, msg_ts: Optional[float]) -> None:
        # Advance the persisted cursor and refresh the in-memory last_seen_ts
        # (the latter is for log readability only and is not persisted).
        self.cursor[dest_name] = msg_key
        if msg_ts is not None:
            self.last_seen_ts[dest_name] = float(msg_ts)

    def forward_msg(self, msg: dict[str, Any]) -> bool:
        # Forward a single message through every configured rule.
        # For each rule, apply filters, then attempt delivery per destination
        # using the rule's strategy. Advance `cursor` per destination so
        # already-delivered (or filtered-out) messages are not retried.
        msg['source'] = self.source
        msg_key = msg.get(self.CURSOR_FIELD)
        msg_ts = msg.get('timestamp')
        if not isinstance(msg_key, (int, float)) or isinstance(msg_key, bool):
            raise ValueError(
                f"msg missing numeric cursor field '{self.CURSOR_FIELD}': {msg_key!r}"
            )
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
                    if msg_key > self.cursor.get(dest_name, -1):
                        self._advance_cursor(dest_name, msg_key, msg_ts)
                continue

            attempted = 0
            any_success = False
            any_failed = False
            errors = []

            for idx, dest in enumerate(rule_dests):
                dest_name = dest["name_mark"]
                dest_mark = f"{dest.get('logmarker')} {dest_name}({dest.get('channel')})"
                last_key = self.cursor.get(dest_name, -1)
                key_passed = msg_key > last_key
                logger.debug(
                    f"{dest_mark} cursor "
                    f"{'[√]' if key_passed else '[x]'}: "
                    f"{msg_key} {'>' if key_passed else '<='} {last_key}"
                )
                if not key_passed:
                    # This destination has already been updated past msg_key
                    # (e.g. delivered previously), skip.
                    continue

                rendered_dest = render_destination(dest, msg, is_alarm=False)
                cur_status, cur_res = self._send_to_destination(rendered_dest)

                attempted += 1
                if cur_status:
                    any_success = True
                    self._advance_cursor(dest_name, msg_key, msg_ts)
                    if rule_strategy == "until_success":
                        # Short-circuit: mark remaining destinations as caught up
                        # to avoid re-sending this msg to them later.
                        for remaining in rule_dests[idx + 1:]:
                            r_name = remaining["name_mark"]
                            if msg_key > self.cursor.get(r_name, -1):
                                self._advance_cursor(r_name, msg_key, msg_ts)
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
        # Subclasses must return a list of new-message dicts sorted by the
        # cursor field, each containing at minimum:
        # - `timestamp` (float seconds since epoch), for templates/logs
        # - `self.CURSOR_FIELD` (int), the monotonic cursor key
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
        # Reset cursors from "DB tail" (ignore saved record) so all mock msgs
        # pass the cursor gate.
        self.init_cursor(load_saved=False)

        base_key = self.min_cursor
        base_ts = time.time()
        for idx, msg in enumerate(new_msgs):
            msg[self.CURSOR_FIELD] = base_key + idx + 1
            msg["timestamp"] = base_ts + idx + 1
            msg["time_str"] = format_ts(msg["timestamp"])

        try:
            self.send_alarm(error=f"mock starting ({self.KIND})")
            self.check_to_forward(mock=True, mock_msgs=new_msgs)
        except Exception as e:
            traceback.print_exc()
            self.send_alarm(error=str(e), traceback=traceback.format_exc())

    def check_to_forward(self, mock: bool = False, mock_msgs: list[dict[str, Any]] = []) -> None:
        # One tick of the main loop: fetch new messages and forward each of them.
        # Also handles the "no new message for 24h" watchdog.
        self.min_cursor = min(self.cursor.values()) if self.cursor else 0.0
        logger.debug(
            f"[{self.KIND}] cursor: "
            f"{ {k: f'{v}({format_ts(self.last_seen_ts[k])})' if k in self.last_seen_ts else str(v) for k, v in self.cursor.items()} }"
        )
        logger.debug(f"[{self.KIND}] min_cursor: {self.min_cursor}")
        c_timestamp = time.time()

        new_msgs = mock_msgs if mock else self.query_new_msgs()

        if new_msgs:
            self.last_new_msg_time = c_timestamp
            for msg in new_msgs:
                try:
                    print("")
                    logger.info(f"{'>' * 15} {self.NEW_MSG_HIT} {self.KIND} {'<' * 15}")
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

            self.write_record_to_file(mock)

        elif self.is_1st_start:
            # On the very first tick, persist the initial state so a fresh run
            # leaves a record file on disk even if no new message arrived.
            self.write_record_to_file(mock)

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
