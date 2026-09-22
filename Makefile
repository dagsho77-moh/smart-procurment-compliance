PY ?= python

.PHONY: setup synth index process process-mock test lint evaluate clean

setup:
	$(PY) -m pip install -r requirements-dev.txt
	$(PY) -m pip install -e .
	@test -f .env || cp .env.example .env

synth:
	$(PY) -m invoice_guard synth --count 8 --seed 42

index:
	$(PY) -m invoice_guard index

process:
	$(PY) -m invoice_guard process data/synthetic_invoices --reset

process-mock:
	LLM_PROVIDER=mock $(PY) -m invoice_guard process data/synthetic_invoices --reset

test:
	LLM_PROVIDER=mock $(PY) -m pytest -q

lint:
	ruff check src tests scripts
	lint-imports

evaluate:
	$(PY) -m invoice_guard evaluate

clean:
	rm -rf data/runtime/* reports/*
	touch data/runtime/.gitkeep reports/.gitkeep
