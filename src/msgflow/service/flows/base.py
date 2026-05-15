import os, sys, time, json, random, traceback, logging
from typing import Any, Optional
import regex

from ...common.run_models import RunStatus, RunTriggerType
from ...common.templating import render_destination
from ...common.utils import format_ts, get_code_from_text
from ..channels import Channels, CHANNEL_NOTIFIERS, LOCAL_CHANNELS

logger = logging.getLogger(__name__)
MANAGED_CORE_ENV = "MSGFLOW_MANAGED_CORE"


def _observe_log(message: str) -> None:
    level = logging.DEBUG if os.environ.get(MANAGED_CORE_ENV) else logging.INFO
    logger.log(level, message)


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
    def __init__(self, runtime: Optional[Any] = None) -> None:
        from ... import config as _config
        super().__init__()
        if not self.CURSOR_FIELD:
            raise ValueError(f"{type(self).__name__} did not set CURSOR_FIELD")
        self.runtime = runtime
        self.is_1st_start = True
        # Persisted: per-destination last-forwarded cursor key. The cursor is
        # monotonically increasing within a given flow (e.g. ROWID for SMS,
        # delivered_date for notifications) but its concrete type is chosen
        # by the subclass — int or float both work as long as `>` orders them
        # correctly and JSON round-trips losslessly.
        self.cursor: dict[str, float] = {}
        # Destinations whose cursor changed since the last successful DB flush.
        self.dirty_destinations: set[str] = set()
        # In-memory only: last seen message timestamp per dest, for readable logs.
        self.last_seen_ts: dict[str, float] = {}
        self.built_cfg = _config.cfg.built_cfg
        self.rules = self.built_cfg.get(self.KIND, {}).get('rules', [])
        self.destinations = self._flatten_destinations()
        self.alarm_strategy = self.built_cfg['alarm']['strategy']
        self.alarm_destinations = self.built_cfg['alarm']['destinations']
        self.source = self.built_cfg.get('source')
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
        saved_cursor = self._load_saved_cursor() if load_saved else {}

        db_tail = self.initial_cursor()
        for dest in self.destinations:
            dest_name = dest['name_mark']
            # Local-only channels (e.g. macOS notification) are not persisted:
            # they are side effects on the current machine, not remote delivery,
            # so always start from the DB tail to avoid spamming on restart.
            if dest.get('channel') in LOCAL_CHANNELS:
                self.cursor[dest_name] = db_tail
                continue
            if dest_name in saved_cursor:
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

    def _load_saved_cursor(self) -> dict[str, float]:
        if self.runtime is None:
            return {}
        rows = self.runtime.history.get_cursor_map(self.KIND)
        return {row["destination"]: float(row["cursor_value"]) for row in rows}

    def persist_cursor_state(self, mock: bool = False, full_snapshot: bool = False) -> None:
        # Persist the current per-destination cursor snapshot into SQLite.
        # The whole snapshot/update-set is committed in one DB transaction so a
        # restart never sees a half-written mix of old/new destination cursors.
        # Normal message processing flushes only destinations whose cursor
        # changed. The first idle tick still forces a full snapshot so a
        # brand-new install creates the initial DB state even before any real
        # forwarding has happened.
        self.is_1st_start = False
        if mock or self.runtime is None:
            return
        if full_snapshot:
            candidate_destinations = [
                dest["name_mark"]
                for dest in self.destinations
                if dest.get("channel") not in LOCAL_CHANNELS
            ]
        else:
            if not self.dirty_destinations:
                return
            candidate_destinations = sorted(self.dirty_destinations)
        cursor_map: dict[str, float] = {}
        for dest_name in candidate_destinations:
            cursor_value = self.cursor.get(dest_name)
            if cursor_value is None:
                continue
            cursor_map[dest_name] = float(cursor_value)
        self.runtime.history.set_cursor_map(self.KIND, cursor_map)
        if not full_snapshot:
            self.dirty_destinations.difference_update(cursor_map.keys())

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
                    _observe_log(f"🕸️  filter [x]: {json.dumps(f, ensure_ascii=False, default=str)}")
                    return False
                else:
                    _observe_log(f"🕸️  filter [√]: {json.dumps(f, ensure_ascii=False, default=str)}")
            return True
        _observe_log("🕸️  no filters")
        return True

    def _build_filter_results(
        self,
        msg: dict[str, Any],
        filters: Optional[list[dict[str, Any]]],
    ) -> tuple[bool, list[dict[str, Any]]]:
        if not filters:
            _observe_log("🕸️  no filters")
            return True, []
        results = []
        all_matched = True
        for idx, cur_filter in enumerate(filters):
            cur_matched = self.is_filter_matched(msg, cur_filter['match'], cur_filter['type'])
            _observe_log(
                f"🕸️  filter [{'√' if cur_matched else 'x'}]: "
                f"{json.dumps(cur_filter, ensure_ascii=False, default=str)}"
            )
            if not cur_matched:
                all_matched = False
            results.append(
                {
                    "index": idx,
                    "type": cur_filter.get("type"),
                    "content": cur_filter,
                    "matched": cur_matched,
                }
            )
        return all_matched, results

    def _build_template_context(self, raw_msg: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": self.source,
            "code": get_code_from_text(raw_msg.get("text")),
        }

    def _build_run_status(
        self,
        sent_dest_count: int,
        success_dest_count: int,
        failed_dest_count: int,
    ) -> str:
        if sent_dest_count == 0:
            return RunStatus.SKIPPED.value
        if failed_dest_count == 0:
            return RunStatus.SUCCESS.value
        if success_dest_count == 0:
            return RunStatus.FAILED.value
        return RunStatus.PARTIAL.value

    def process_message(
        self,
        msg: dict[str, Any],
        trigger_type: str = RunTriggerType.AUTO.value,
        message_id: Optional[int] = None,
        selected_rule: Optional[str] = None,
        selected_dest: Optional[str] = None,
        persist_message: bool = False,
        advance_cursor: bool = True,
        enable_alarm: bool = True,
    ) -> dict[str, Any]:
        raw_msg = dict(msg)
        logger.debug(f"📨 {json.dumps(raw_msg, ensure_ascii=False, default=str)}")
        if persist_message and self.runtime is not None:
            message_id = self.runtime.history.insert_message(self.KIND, self.CURSOR_FIELD, raw_msg)
            self.runtime.history_inserted()
        template_context = self._build_template_context(raw_msg)
        msg = {**raw_msg, **template_context}
        msg_code = msg.get("code")
        if msg_code:
            _observe_log(f"🔐 {msg_code}")
        msg["msg"] = json.dumps(msg, ensure_ascii=False, default=str)
        msg_key = msg.get(self.CURSOR_FIELD)
        msg_ts = msg.get("timestamp")

        matched_rule_count = 0
        sent_dest_count = 0
        success_dest_count = 0
        failed_dest_count = 0
        result_trace = {
            "run_meta": {
                "advance_cursor": advance_cursor,
                "selected_rule": selected_rule,
                "selected_destination": selected_dest,
            },
            "rules": [],
        }

        for rule in self.rules:
            rule_name = rule.get("name_mark")
            if selected_rule and rule_name != selected_rule:
                continue
            rule_filters = rule.get("filters")
            rule_strategy = rule.get("strategy")
            rule_dests = rule.get("destinations") or []
            _observe_log(f"📏 {rule_name}({rule_strategy})")

            filters_matched, filter_results = self._build_filter_results(msg, rule_filters)
            if filters_matched:
                matched_rule_count += 1

            rule_result = {
                "name_mark": rule_name,
                "strategy": rule_strategy,
                "matched": filters_matched,
                "filters": filter_results,
                "destinations": [],
            }
            result_trace["rules"].append(rule_result)
            dest_results_by_name: dict[str, dict[str, Any]] = {}
            for dest in rule_dests:
                dest_name = dest["name_mark"]
                if selected_dest and dest_name != selected_dest:
                    continue
                last_key = self.cursor.get(dest_name, -1)
                dest_result = {
                    "name_mark": dest_name,
                    "channel": dest.get("channel"),
                    "attempted": False,
                    "cursor_allowed": True if not advance_cursor else msg_key > last_key,
                    "manual_override": bool(trigger_type == RunTriggerType.RESEND.value and not filters_matched),
                    "rendered_destination": None,
                    "success": None,
                    "response_text": None,
                    "error_text": None,
                }
                rule_result["destinations"].append(dest_result)
                dest_results_by_name[dest_name] = dest_result

            if not filters_matched and trigger_type != RunTriggerType.RESEND.value:
                if advance_cursor:
                    for dest in rule_dests:
                        dest_name = dest["name_mark"]
                        if selected_dest and dest_name != selected_dest:
                            continue
                        if msg_key > self.cursor.get(dest_name, -1):
                            self._advance_cursor(dest_name, msg_key, msg_ts)
                continue

            attempted = 0
            any_success = False
            any_failed = False
            errors = []

            for idx, dest in enumerate(rule_dests):
                dest_name = dest["name_mark"]
                if selected_dest and dest_name != selected_dest:
                    continue
                dest_mark = f"{dest.get('logmarker')} {dest_name}({dest.get('channel')})"
                last_key = self.cursor.get(dest_name, -1)
                dest_result = dest_results_by_name[dest_name]
                key_passed = bool(dest_result["cursor_allowed"])
                logger.debug(
                    f"{dest_mark} cursor "
                    f"{'[√]' if key_passed else '[x]'}: "
                    f"{msg_key} {'>' if key_passed else '<='} {last_key}"
                )
                if not key_passed:
                    continue

                rendered_dest = render_destination(dest, msg, is_alarm=False)
                dest_result["rendered_destination"] = rendered_dest
                cur_status, cur_res = self._send_to_destination(rendered_dest)

                attempted += 1
                sent_dest_count += 1
                dest_result["attempted"] = True
                if cur_status:
                    any_success = True
                    success_dest_count += 1
                    dest_result["success"] = True
                    dest_result["response_text"] = cur_res
                    if advance_cursor:
                        self._advance_cursor(dest_name, msg_key, msg_ts)
                    if rule_strategy == "until_success":
                        if advance_cursor:
                            # This rule has been satisfied by `dest_name`, so the
                            # current message should be considered consumed for
                            # every destination in the same rule. Otherwise an
                            # earlier failed destination (for example a local
                            # floating panel) would keep `min_cursor` pinned
                            # behind the message and cause it to be fetched again
                            # on the next polling tick.
                            for previous in rule_dests[:idx]:
                                p_name = previous["name_mark"]
                                if selected_dest and p_name != selected_dest:
                                    continue
                                if msg_key > self.cursor.get(p_name, -1):
                                    self._advance_cursor(p_name, msg_key, msg_ts)
                            for remaining in rule_dests[idx + 1:]:
                                r_name = remaining["name_mark"]
                                if selected_dest and r_name != selected_dest:
                                    continue
                                if msg_key > self.cursor.get(r_name, -1):
                                    self._advance_cursor(r_name, msg_key, msg_ts)
                        break
                else:
                    any_failed = True
                    failed_dest_count += 1
                    dest_result["success"] = False
                    dest_result["error_text"] = str(cur_res)
                    logger.error(f"❌ forward_{self.KIND} failed: {cur_res}")
                    errors.append(f"{cur_res}")

            if enable_alarm:
                if rule_strategy == "all":
                    if attempted > 0 and any_failed:
                        self.send_alarm(
                            msg,
                            error=f"({rule_strategy}) some destinations failed",
                            traceback="\n\n".join(errors) if errors else None,
                        )
                else:
                    if attempted > 0 and (not any_success):
                        self.send_alarm(
                            msg,
                            error=f"({rule_strategy}) all destinations failed",
                            traceback="\n\n".join(errors) if errors else None,
                        )

        status = self._build_run_status(
            sent_dest_count=sent_dest_count,
            success_dest_count=success_dest_count,
            failed_dest_count=failed_dest_count,
        )

        run_id: Optional[int] = None
        if self.runtime is not None and message_id is not None:
            run_id = self.runtime.history.insert_run(
                message_id=message_id,
                code=msg_code,
                trigger_type=trigger_type,
                status=status,
                matched_rule_count=matched_rule_count,
                sent_dest_count=sent_dest_count,
                success_dest_count=success_dest_count,
                failed_dest_count=failed_dest_count,
                trace=result_trace,
            )
            if trigger_type == RunTriggerType.AUTO.value:
                self.runtime.maybe_cleanup_history()
        return {
            "status": status,
            "run_id": run_id,
        }

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
        self.dirty_destinations.add(dest_name)
        if msg_ts is not None:
            self.last_seen_ts[dest_name] = float(msg_ts)

    # ---------- Main loop entrypoint ----------

    def query_new_msgs(self) -> list[dict[str, Any]]:
        # Subclasses must return a list of new-message dicts sorted by the
        # cursor field, each containing at minimum:
        # - `timestamp` (float seconds since epoch), for templates/logs
        # - `self.CURSOR_FIELD` (int), the monotonic cursor key
        raise NotImplementedError

    def mock_to_forward(self, num: int, fixture_file: str) -> None:
        # Mock mode: replay explicit fixture data so test samples stay outside
        # the shipped product bundle.
        with open(fixture_file, 'r') as f:
            msgs_list = json.load(f)
        source_label = fixture_file
        if not isinstance(msgs_list, list):
            raise ValueError(f"invalid mock data format ({source_label}), expected list, got {type(msgs_list)}")
        if not msgs_list:
            raise ValueError(f"no mock messages available from {source_label}")
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
                    _observe_log(f"{'>' * 15} {self.NEW_MSG_HIT} {self.KIND} {'<' * 15}")
                    self.process_message(
                        msg,
                        trigger_type=RunTriggerType.AUTO.value,
                        persist_message=bool(self.runtime is not None),
                        advance_cursor=True,
                        enable_alarm=True,
                    )
                    self.persist_cursor_state(mock)
                except Exception as e:
                    traceback.print_exc()
                    self.send_alarm(msg=msg, error=str(e), traceback=traceback.format_exc())
                    continue
                finally:
                    _observe_log(f"{'>' * 15} {self.DONE_MSG_HIT} {self.KIND} {'<' * 15}")

        elif self.is_1st_start:
            # On the very first tick, persist the initial state so a fresh run
            # leaves an initialized DB cursor snapshot even if no new message
            # arrived yet.
            self.persist_cursor_state(mock, full_snapshot=True)

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

    def close(self) -> None:
        db = getattr(self, "db", None)
        if db is None:
            return
        close = getattr(db, "close", None)
        if callable(close):
            close()
