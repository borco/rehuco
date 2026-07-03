.PHONY: sync tests cov format bandit pyright pylint qa docs-serve publish setup-git uis qrcs icons \
	agent-build agent-build-clean agent-register agent-unregister

SEARCH_DIRS := apps packages spikes
# pyside6-uic --python-paths uses the OS-native path separator (os.pathsep): ';' on Windows,
# ':' elsewhere. Hardcoding ';' made uic see one nonexistent path on macOS/Linux, so it could
# not resolve a .ui's .qrc to its package and fell back to a bare `import <name>_rc`.
ifeq ($(OS),Windows_NT)
PATHSEP := ;
else
PATHSEP := :
endif
PYTHON_PATHS := $(shell find apps packages -maxdepth 3 -name src -type d | tr '\n' '$(PATHSEP)' | sed 's/$(PATHSEP)$$//')
UI_FILES   := $(patsubst %.ui,%_ui.py,$(shell find $(SEARCH_DIRS) -name '*.ui'  -print 2>/dev/null))
QRC_FILES  := $(patsubst %.qrc,%_rc.py,$(shell find $(SEARCH_DIRS) -name '*.qrc' -print 2>/dev/null))
# Brand icons live in a single top-level design/icons/ (issue #29): the Affinity Designer master
# plus its exports. Consumers reference them in place -- qrc aliases (agent) and CMake (launcher);
# only the docs site needs copies, since mkdocs can't read outside docs_dir.
ICON_DIR    := design/icons
ICON_FILES  := $(ICON_DIR)/rehuco-agent.ico
DOCS_IMAGES := docs/assets/images
DOCS_ICONS  := $(DOCS_IMAGES)/favicon.svg $(DOCS_IMAGES)/logo.svg

uis: qrcs $(UI_FILES)

# qrcs no longer depends on icons: the qrc embeds only the .svg (referenced in place from
# design/icons via an alias), not the .ico -- so a qrc rebuild doesn't need ImageMagick. The
# launcher target depends on $(ICON_FILES) directly for the .ico it embeds in the exe.
qrcs: $(QRC_FILES)

icons: $(ICON_FILES) $(DOCS_ICONS)

%_ui.py: %.ui
	uv run pyside6-uic $< --absolute-imports --python-paths "$(PYTHON_PATHS)" -o $@

%_rc.py: %.qrc
	uv run pyside6-rcc $< -o $@

# .ico is built by downscaling the 1024px PNG master (reliable), not by rasterizing the SVG
# (ImageMagick's SVG rasterizer is unreliable). The launcher's RC compiler embeds it in the exe.
%.ico: %.png
	magick $< -background none -define icon:auto-resize=16,24,32,48,64,128,256 $@

# The docs site can't read outside docs_dir, so copy favicon + logo in. Real file targets give
# the newer-than behaviour for free: make re-copies only when the design/icons source changed.
$(DOCS_IMAGES)/favicon.svg: $(ICON_DIR)/favicon.svg
	cp $< $@

$(DOCS_IMAGES)/logo.svg: $(ICON_DIR)/rehuco-agent.svg
	cp $< $@

setup-git:
	git config --replace-all remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
	git config --add remote.origin.fetch "^refs/heads/gh-pages"
	git branch -dr origin/gh-pages 2>/dev/null || true

sync:
	uv sync

tests:
	uv run pytest

cov:
	uv run pytest --cov=rehuco_agent --cov=rehuco_core --cov=rehuco_node --cov=borco_core --cov=borco_pyside --cov-report=term-missing --cov-report=xml

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

# Windows-only, dev-only (apps/rehuco-agent/launcher): a local double-click/registration
# target with correct app identity, running the live editable install. Requires VS2022 and
# `cmake` on PATH (`scoop install cmake` if missing -- see apps/rehuco-agent/launcher/README.md).
# Never touched by qa/tests/publish or a real Briefcase build. Build output goes in .build/,
# mirroring the source path, alongside this repo's other generated-artifact dot-dirs (.dist/ etc).
AGENT_LAUNCHER_BUILD := .build/apps/rehuco-agent/launcher
AGENT_DEV_EXE := $(AGENT_LAUNCHER_BUILD)/Release/rehuco-agent-dev.exe

AGENT_LAUNCHER_SRC := apps/rehuco-agent/launcher/launcher.c apps/rehuco-agent/launcher/CMakeLists.txt \
	apps/rehuco-agent/launcher/config.h.in apps/rehuco-agent/launcher/launcher.rc.in

# $(AGENT_DEV_EXE) (not agent-build itself) is the real target, so make only re-invokes cmake
# when a source/icon actually changed -- cmake's own incremental build already no-ops
# correctly, but agent-build was PHONY, so make re-ran the (admittedly then-fast) cmake
# configure+build every time regardless. Depends on $(ICON_FILES) directly, not the `icons`
# label -- `icons` is itself PHONY, and a real target depending on a phony one is always
# considered out of date, which would defeat this whole fix. launcher.rc.in embeds the .ico
# into the exe's PE resources at build time, so it must exist before cmake configures/builds,
# not just before registering.
agent-build: $(AGENT_DEV_EXE)

$(AGENT_DEV_EXE): $(AGENT_LAUNCHER_SRC) $(ICON_FILES)
	cmake -S apps/rehuco-agent/launcher -B $(AGENT_LAUNCHER_BUILD) -G "Visual Studio 17 2022" -A x64
	cmake --build $(AGENT_LAUNCHER_BUILD) --config Release

agent-build-clean:
	rm -rf $(AGENT_LAUNCHER_BUILD)

# --register/--unregister route through rehuco-agent-dev.exe itself (its entry script calls
# rehuco_agent.__main__:main(), same as the real packaged CLI) -- it registers itself, not the
# packaged rehuco-agent.exe, since __main__.main() keys off sys.argv[0].
agent-register: agent-build
	"$(AGENT_DEV_EXE)" --register

agent-unregister: agent-build
	"$(AGENT_DEV_EXE)" --unregister
