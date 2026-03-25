UV ?= uv

.PHONY: fmt types

fmt:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

types:
	$(UV) run mypy .
