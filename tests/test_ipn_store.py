import plistlib

from msgflow.service.flows import ipn_store
from msgflow.service.flows.ipn_store import MAC_EPOCH_OFFSET, RemoteNotificationStore, creation_date_to_cursor


def _archive(root_uid: int, objects: list[object]) -> dict[str, object]:
    return {
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$top": {"root": plistlib.UID(root_uid)},
        "$objects": objects,
    }


def _class(name: str) -> dict[str, object]:
    return {"$classname": name, "$classes": [name, "NSObject"]}


def _dict_object(keys: list[int], values: list[int]) -> dict[str, object]:
    return {
        "$class": plistlib.UID(1),
        "NS.keys": [plistlib.UID(idx) for idx in keys],
        "NS.objects": [plistlib.UID(idx) for idx in values],
    }


def _array_object(values: list[int]) -> dict[str, object]:
    return {
        "$class": plistlib.UID(2),
        "NS.objects": [plistlib.UID(idx) for idx in values],
    }


def _date_object(unix_ts: float) -> dict[str, object]:
    return {
        "$class": plistlib.UID(3),
        "NS.time": unix_ts - MAC_EPOCH_OFFSET,
    }


def test_remote_notification_store_decodes_messages(tmp_path):
    root, app_uuid, created_at = _write_store_fixture(tmp_path)

    messages = RemoteNotificationStore(root).load_notifications()

    assert messages == [
        {
            "ipn_cursor": creation_date_to_cursor(created_at),
            "sender": "com.example.ios",
            "time_str": messages[0]["time_str"],
            "timestamp": created_at,
            "title": "Title",
            "subtitle": "",
            "body": "Body",
            "msg": {
                "AppNotificationCreationDate": created_at,
                "AppNotificationIdentifier": "notification-1",
                "AppNotificationTitle": "Title",
                "AppNotificationMessage": "Body",
                "event_details": {},
                "app_uuid": app_uuid,
                "bundle_id": "com.example.ios",
                "notification_id": "notification-1",
            },
        }
    ]


def test_remote_notification_store_decodes_keyed_archive_null_as_none(tmp_path):
    root, _app_uuid, _created_at = _write_store_fixture(tmp_path, include_null_event_details=True)

    message = RemoteNotificationStore(root).load_notifications()[0]

    assert message["title"] == "Title"
    assert message["subtitle"] == ""
    assert message["body"] == "Body"
    assert message["msg"]["event_details"] == {
        "title": None,
        "subtitle": None,
        "body": "Body",
    }


def test_remote_notification_store_retries_delivered_decode(tmp_path, monkeypatch):
    root, _app_uuid, _created_at = _write_store_fixture(tmp_path)
    original_decode = ipn_store._decode_keyed_archive
    calls = {"delivered": 0}

    def flaky_decode(path):
        if path.name == "DeliveredNotifications.plist":
            calls["delivered"] += 1
            if calls["delivered"] == 1:
                raise plistlib.InvalidFileException()
        return original_decode(path)

    monkeypatch.setattr(ipn_store, "_decode_keyed_archive", flaky_decode)
    monkeypatch.setattr(ipn_store.time, "sleep", lambda _seconds: None)

    messages = RemoteNotificationStore(root).load_notifications()

    assert calls["delivered"] == 2
    assert len(messages) == 1
    assert messages[0]["sender"] == "com.example.ios"


def test_remote_notification_store_keeps_last_library_mapping_on_decode_failure(tmp_path):
    root, _app_uuid, _created_at = _write_store_fixture(tmp_path)
    store = RemoteNotificationStore(root)
    assert store.load_notifications()[0]["sender"] == "com.example.ios"

    (root / "Library.plist").write_bytes(b"not a plist")
    messages = store.load_notifications()

    assert messages[0]["sender"] == "com.example.ios"


def test_message_from_item_uses_event_behavior_details_and_prunes_raw_msg(tmp_path):
    store = RemoteNotificationStore(tmp_path)
    created_at = 1_778_956_385.220458
    msg = store._message_from_item(
        "APP-UUID",
        {
            "AppNotificationCreationDate": created_at,
            "AppNotificationIdentifier": b"notification-bytes",
            "Unrelated": "drop",
            "EventBehavior": {
                "eventDetails": {
                    "title": b"Event title",
                    "subtitle": "Event subtitle",
                    "body": bytearray(b"Event body"),
                },
            },
        },
    )

    assert msg is not None
    assert msg["title"] == "Event title"
    assert msg["subtitle"] == ""
    assert msg["body"] == "Event body"
    assert msg["msg"] == {
        "AppNotificationCreationDate": created_at,
        "AppNotificationIdentifier": "notification-bytes",
        "event_details": {
            "title": "Event title",
            "subtitle": "Event subtitle",
            "body": "Event body",
        },
        "app_uuid": "APP-UUID",
        "bundle_id": "APP-UUID",
        "notification_id": "notification-bytes",
    }


def _write_store_fixture(tmp_path, include_null_event_details: bool = False):
    root = tmp_path / "Remote" / "default"
    app_uuid = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    app_dir = root / app_uuid
    app_dir.mkdir(parents=True)
    library_objects = [
        "$null",
        _class("NSMutableDictionary"),
        "com.example.ios",
        app_uuid,
        _dict_object([2], [3]),
    ]
    (root / "Library.plist").write_bytes(plistlib.dumps(_archive(4, library_objects), fmt=plistlib.FMT_BINARY))

    created_at = 1_778_956_385.220458
    delivered_objects = [
        "$null",
        _class("NSMutableDictionary"),
        _class("NSArray"),
        _class("NSDate"),
        "AppNotificationCreationDate",
        "AppNotificationIdentifier",
        "AppNotificationTitle",
        "AppNotificationMessage",
        _date_object(created_at),
        "notification-1",
        "Title",
        "Body",
    ]
    if include_null_event_details:
        delivered_objects.extend(
            [
                "EventBehavior",
                "eventDetails",
                "title",
                "subtitle",
                "body",
                _dict_object([14, 15, 16], [0, 0, 11]),
                _dict_object([13], [17]),
                _dict_object([4, 5, 6, 7, 12], [8, 9, 10, 11, 18]),
                _array_object([19]),
            ]
        )
    else:
        delivered_objects.extend(
            [
                _dict_object([4, 5, 6, 7], [8, 9, 10, 11]),
                _array_object([12]),
            ]
        )
    (app_dir / "DeliveredNotifications.plist").write_bytes(
        plistlib.dumps(_archive(len(delivered_objects) - 1, delivered_objects), fmt=plistlib.FMT_BINARY)
    )
    return root, app_uuid, created_at
