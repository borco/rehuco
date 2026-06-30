.PHONY: sync tests format pylint qa docs-serve publish setup-git

setup-git:
	git config --replace-all remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
	git config --add remote.origin.fetch "^refs/heads/gh-pages"
	git branch -dr origin/gh-pages 2>/dev/null || true

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

publish:
	uv build --all-packages --out-dir .dist
	uv publish --check-url https://pypi.org/simple/ .dist/*
