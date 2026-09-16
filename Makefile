PY := ./.venv/bin/python
FF := ./.venv/bin/ff

.PHONY: install test test-live lint typecheck build check hooks run fixtures clean

install:               ## create venv + install package (editable) with dev deps
	python3 -m venv .venv
	$(PY) -m pip install -U pip setuptools wheel
	$(PY) -m pip install -e ".[dev]"
	git config core.hooksPath .githooks

test:                  ## gate suite: offline, deterministic, < 2s
	$(PY) -m pytest -q

test-live:             ## hit the real Sleeper + FantasyCalc APIs (set FF_LIVE_LEAGUE_ID for the draft-shape check)
	$(PY) -m pytest -m live

lint:                  ## check code style & unused imports with ruff
	$(PY) -m ruff check

typecheck:             ## check static typing with mypy
	$(PY) -m mypy src

build:                 ## verify PEP 517 package build
	uv build

check: lint typecheck test build ## run all verification checks

hooks:                 ## enable the pre-commit gate
	git config core.hooksPath .githooks

run:                   ## e.g. make run ARGS="trade --give 'Gibbs' --get '2027 1st'"
	$(FF) $(ARGS)

fixtures:              ## snapshot a real league: make fixtures LEAGUE=<id>
	$(PY) scripts/record_fixtures.py $(LEAGUE)

clean:                 ## drop local cache + config
	rm -rf .ff
