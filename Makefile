.PHONY: sync tests format pylint qa docs-serve

sync:
	uv sync

tests:
	uv run pytest

format:
	uv run ruff format .
	uv run ruff check --fix .

pylint:
	uv run pylint packages/ apps/

qa: format tests pylint

docs-serve:
	uv run mkdocs serve
