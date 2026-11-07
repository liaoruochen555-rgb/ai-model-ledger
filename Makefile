.PHONY: install test check sync build

install:
	pip install -e ".[dev]"

test:
	pytest

check:
	ai-model-ledger check

sync:
	ai-model-ledger sync

build:
	ai-model-ledger build --out site
