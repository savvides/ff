PY := ./.venv/bin/python
FF := ./.venv/bin/ff

.PHONY: install test test-live hooks run fixtures clean

install:               ## create venv + install package (editable) with dev deps
	python3 -m venv .venv
	$(PY) -m pip install -U pip setuptools wheel
	$(PY) -m pip install -e ".[dev]"
	git config core.hooksPath .githooks

test:                  ## gate suite: offline, deterministic, < 2s
	$(PY) -m pytest -q

test-live:             ## hit the real Sleeper + FantasyCalc APIs
	$(PY) -m pytest -m live

hooks:                 ## enable the pre-commit gate
	git config core.hooksPath .githooks

run:                   ## e.g. make run ARGS="trade --give 'Gibbs' --get '2027 1st'"
	$(FF) $(ARGS)

fixtures:              ## snapshot a real league: make fixtures LEAGUE=<id>
	$(PY) scripts/record_fixtures.py $(LEAGUE)

clean:                 ## drop local cache + config
	rm -rf .ff
