import logging

from msgflow.service.flows import base


def test_observe_log_uses_info_for_external_core(monkeypatch, caplog):
    monkeypatch.delenv(base.MANAGED_CORE_ENV, raising=False)
    caplog.set_level(logging.DEBUG, logger=base.logger.name)

    base._observe_log("external message")

    assert ("msgflow.service.flows.base", logging.INFO, "external message") in caplog.record_tuples


def test_observe_log_uses_debug_for_managed_core(monkeypatch, caplog):
    monkeypatch.setenv(base.MANAGED_CORE_ENV, "1")
    caplog.set_level(logging.DEBUG, logger=base.logger.name)

    base._observe_log("managed message")

    assert ("msgflow.service.flows.base", logging.DEBUG, "managed message") in caplog.record_tuples
