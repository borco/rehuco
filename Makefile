.PHONY: sync tests cov format bandit pyright pylint qa docs-serve publish setup-git uis qrcs

SEARCH_DIRS := apps packages spikes
PYTHON_PATHS := $(shell find apps packages -maxdepth 3 -name src -type d | tr '\n' ';' | sed 's/;$$//')
UI_FILES  := $(patsubst %.ui,%_ui.py,$(shell find $(SEARCH_DIRS) -name '*.ui'  -print 2>/dev/null))
QRC_FILES := $(patsubst %.qrc,%_rc.py,$(shell find $(SEARCH_DIRS) -name '*.qrc' -print 2>/dev/null))

uis: qrcs $(UI_FILES)

qrcs: $(QRC_FILES)

%_ui.py: %.ui
	uv run pyside6-uic $< --absolute-imports --python-paths "$(PYTHON_PATHS)" -o $@

%_rc.py: %.qrc
	uv run pyside6-rcc $< -o $@

setup-git:
	git config --replace-all remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
	git config --add remote.origin.fetch "^refs/heads/gh-pages"
	git branch -dr origin/gh-pages 2>/dev/null || true

sync:
	uv sync

tests:
	uv run pytest

cov:
	uv run pytest --cov=rehuco_agent --cov=rehuco_core --cov=rehuco_node --cov=borco_core --cov=borco_pyside --cov-report=term-missing

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
