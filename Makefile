.PHONY: sync tests cov format bandit pyright pylint qa docs-serve publish setup-git

setup-git:
	git config --replace-all remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
	git config --add remote.origin.fetch "^refs/heads/gh-pages"
	git branch -dr origin/gh-pages 2>/dev/null || true

sync:
	uv sync

tests:
	uv run pytest

cov:
	uv run pytest --cov=rehuco_agent --cov=rehuco_core --cov=rehuco_node --cov-report=term-missing

format:
	uv run ruff format .
	uv run ruff check --fix .

bandit:
	uv run bandit -c pyproject.toml -r packages/ apps/

pyright:
	uv run pyright packages/ apps/

pylint:
	uv run pylint packages/ apps/

qa: format cov bandit pyright pylint

docs-serve:
	uv run mkdocs serve

publish:
	uv build --all-packages --out-dir .dist
	uv publish --check-url https://pypi.org/simple/ .dist/*
