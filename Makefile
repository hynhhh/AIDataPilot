PYTHON ?= python3
UV ?= uv

.PHONY: setup setup-conda lint test check pre-commit-install

setup:
	$(UV) venv --python 3.11
	$(UV) pip install --python .venv/bin/python -r requirements.txt

setup-conda:
	$(PYTHON) -m pip install -r requirements.txt

lint:
	$(PYTHON) -m compileall -q app
	$(PYTHON) -m ruff check --select=E9,F63,F7 app

test:
	@if [ -d tests ]; then $(PYTHON) -m pytest -q; else echo "No tests directory yet; skipped."; fi

check: lint test

pre-commit-install:
	$(PYTHON) -m pre_commit install
