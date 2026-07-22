PYTHON ?= python
API_PORT ?= 8000
WEB_PORT ?= 3000

.PHONY: help bootstrap format lint typecheck test dev docs-check docs-self-test ci

help:
	$(PYTHON) scripts/tasks.py help

bootstrap:
	$(PYTHON) scripts/tasks.py bootstrap

format:
	$(PYTHON) scripts/tasks.py format

lint:
	$(PYTHON) scripts/tasks.py lint

typecheck:
	$(PYTHON) scripts/tasks.py typecheck

test:
	$(PYTHON) scripts/tasks.py test

dev:
	$(PYTHON) scripts/tasks.py dev --port $(API_PORT) --web-port $(WEB_PORT)

docs-check:
	$(PYTHON) scripts/tasks.py docs-check

docs-self-test:
	$(PYTHON) scripts/tasks.py docs-self-test

ci:
	$(PYTHON) scripts/tasks.py ci
