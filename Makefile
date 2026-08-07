PYTHON ?= python
API_PORT ?= 8000
WEB_PORT ?= 3000

.PHONY: help bootstrap format lint typecheck test dev db-up db-down migrate migrate-down db-check docs-check docs-self-test ci

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

db-up:
	$(PYTHON) scripts/tasks.py db-up

db-down:
	$(PYTHON) scripts/tasks.py db-down

migrate:
	$(PYTHON) scripts/tasks.py migrate

migrate-down:
	$(PYTHON) scripts/tasks.py migrate-down

db-check:
	$(PYTHON) scripts/tasks.py db-check

docs-check:
	$(PYTHON) scripts/tasks.py docs-check

docs-self-test:
	$(PYTHON) scripts/tasks.py docs-self-test

ci:
	$(PYTHON) scripts/tasks.py ci
