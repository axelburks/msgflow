SHELL := /bin/bash

PYTHON := .venv/bin/python
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
VERSION ?=
FIXTURE_DIR ?= tests/fixtures
SMS_FIXTURE ?= $(FIXTURE_DIR)/sms/sms.json
NOTIFY_FIXTURE ?= $(FIXTURE_DIR)/notify/notify.json
TEST ?= tests

.PHONY: help venv install install-build install-test verify test test-verbose run-core run-core-debug run-app check \
	mock-sms mock-notify mock-all build smoke-cli smoke-core smoke-app smoke-all clean

help:
	@echo "Available targets:"
	@echo "  make venv            - create local virtualenv"
	@echo "  make install         - install runtime deps and editable package"
	@echo "  make install-build   - install build deps including PyInstaller"
	@echo "  make install-test    - install pytest and test-only deps"
	@echo "  make verify          - run compile-time verification"
	@echo "  make test            - run pytest; override path with TEST=..."
	@echo "  make test-verbose    - run pytest with verbose output"
	@echo "  make run-core        - run core service"
	@echo "  make run-core-debug  - run core service in debug mode"
	@echo "  make run-app         - run macOS app UI"
	@echo "  make check           - send check messages to configured destinations"
	@echo "  make mock-sms        - replay sms fixture"
	@echo "  make mock-notify     - replay notify fixture"
	@echo "  make mock-all        - replay all fixtures from tests/fixtures"
	@echo "  make build           - build release artifacts; defaults to pyproject.toml version"
	@echo "  make smoke-cli       - run packaged CLI binaries"
	@echo "  make smoke-core      - run packaged core binary"
	@echo "  make smoke-app       - open packaged .app"
	@echo "  make smoke-all       - run smoke checks on all packaged outputs"
	@echo "  make clean           - remove build artifacts"

venv:
	python3 -m venv .venv
	$(PIP) install --upgrade pip

install: venv
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

install-build: install
	$(PIP) install pyinstaller

install-test: install
	$(PIP) install pytest

verify:
	python3 -m compileall app.py core.py src scripts/release.py

test:
	$(PYTEST) $(TEST) -q

test-verbose:
	$(PYTEST) $(TEST) -v

run-core:
	$(PYTHON) core.py

run-core-debug:
	$(PYTHON) core.py -d

run-app:
	$(PYTHON) app.py

check:
	$(PYTHON) core.py -c

mock-sms:
	$(PYTHON) core.py -m --kind sms --fixture-file $(SMS_FIXTURE)

mock-notify:
	$(PYTHON) core.py -m --kind notify --fixture-file $(NOTIFY_FIXTURE)

mock-all:
	$(PYTHON) core.py -m --kind all --fixture-dir $(FIXTURE_DIR)

build:
	$(PYTHON) scripts/release.py $(if $(VERSION),--version $(VERSION),) --out-dir release

smoke-cli:
	./dist/msgflow/msgflow

smoke-core:
	./dist/msgflow-core/msgflow-core

smoke-app:
	open dist/msgflow.app

smoke-all: smoke-cli smoke-core
	@echo "Packaged CLI binaries look runnable."
	@echo "Run 'make smoke-app' to open the packaged app."

clean:
	rm -rf build dist release .pyinstaller-cache
