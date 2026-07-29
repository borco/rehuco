.PHONY: sync tests cov format bandit pyright pylint check-slugs qa docs-icons docs-serve docs-build setup-git \
	uis qrcs icons agent-dev-build agent-dev-clean agent-dev-register agent-dev-unregister \
	agent-dist-build agent-dist-update agent-dist-package agent-dist-clean \
	agent-appimage-build agent-appimage-clean

# UTF-8 mode (PEP 540) for every recipe, so a tool printing non-ASCII cannot die on the console's
# encoding. mkdocs-puml ends its run with a "✔️", which a Windows console's default cp1252 stdout
# cannot encode -- the UnicodeEncodeError propagates out of the plugin hook and takes the whole
# mkdocs build/serve down with it. Exported rather than set per docs target: it costs nothing, and
# the next tool to print a check mark shouldn't have to rediscover this.
export PYTHONUTF8 := 1

SEARCH_DIRS := packages spikes
# pyside6-uic --python-paths uses the OS-native path separator (os.pathsep): ';' on Windows,
# ':' elsewhere. Hardcoding ';' made uic see one nonexistent path on macOS/Linux, so it could
# not resolve a .ui's .qrc to its package and fell back to a bare `import <name>_rc`.
ifeq ($(OS),Windows_NT)
PATHSEP := ;
else
PATHSEP := :
endif
PYTHON_PATHS := $(shell find packages -maxdepth 3 -name src -type d | tr '\n' '$(PATHSEP)' | sed 's/$(PATHSEP)$$//')
UI_FILES   := $(patsubst %.ui,%_ui.py,$(shell find $(SEARCH_DIRS) -name '*.ui'  -print 2>/dev/null))
QRC_FILES  := $(patsubst %.qrc,%_rc.py,$(shell find $(SEARCH_DIRS) -name '*.qrc' -print 2>/dev/null))
# Brand icons live in a single top-level design/icons/ (issue #29): the Affinity Designer master
# plus its exports. Consumers reference them in place -- qrc aliases (agent) and CMake (launcher);
# only the docs site needs copies, since mkdocs can't read outside docs_dir.
ICON_DIR    := design/icons
ICON_FILES  := $(ICON_DIR)/rehuco-agent.ico
# The .icns Briefcase's macOS bundle wants is built only on macOS: iconutil is a platform tool with
# no cross-platform equivalent that produces a real multi-resolution icon set, so `make icons`
# elsewhere simply doesn't have one to build.
ifeq ($(shell uname -s),Darwin)
ICON_FILES  += $(ICON_DIR)/rehuco-agent.icns
endif
# WiX's installer chrome. Left unset, the MSI ships the WiX Toolset's own red bitmaps -- someone
# else's branding on our installer. Both are derived from the same PNG master, so `make icons`
# covers them; a hand-designed export from the Affinity master can replace them at these exact
# paths later, with no config change ([[appendices.briefcase-packaging#windows]]).
INSTALLER_DIR    := packages/rehuco-agent/installer
# Windows-only, mirroring the Darwin-only .icns above: only WiX consumes them, and only a Windows
# host can build an MSI at all -- so a macOS/Linux `make icons` has nothing to do here.
ifeq ($(OS),Windows_NT)
INSTALLER_IMAGES := $(INSTALLER_DIR)/background.bmp $(INSTALLER_DIR)/banner.bmp
else
INSTALLER_IMAGES :=
endif
DOCS_IMAGES := docs/assets/images
DOCS_ICONS  := $(DOCS_IMAGES)/favicon.svg $(DOCS_IMAGES)/logo.svg

uis: qrcs $(UI_FILES)

# qrcs no longer depends on icons: the qrc embeds only the .svg (referenced in place from
# design/icons via an alias), not the .ico -- so a qrc rebuild doesn't need ImageMagick. The
# launcher target depends on $(ICON_FILES) directly for the .ico it embeds in the exe.
qrcs: $(QRC_FILES)

icons: $(ICON_FILES) $(DOCS_ICONS) $(INSTALLER_IMAGES)

# The docs site's half of `icons`, on its own: two `cp`s and nothing else. Split out so a docs build
# can depend on it without dragging in ImageMagick, which the rest of `icons` needs for the .ico and
# the WiX bitmaps but the site does not ([[packaging-deployment#design-resources]]).
docs-icons: $(DOCS_ICONS)

%_ui.py: %.ui
	uv run pyside6-uic $< --absolute-imports --python-paths "$(PYTHON_PATHS)" -o $@

%_rc.py: %.qrc
	uv run pyside6-rcc $< -o $@

# .ico is built by downscaling the 1024px PNG master (reliable), not by rasterizing the SVG
# (ImageMagick's SVG rasterizer is unreliable). The launcher's RC compiler embeds it in the exe.
%.ico: %.png
	magick $< -background none -define icon:auto-resize=16,24,32,48,64,128,256 $@

# .icns comes from the same 1024px PNG master, via the macOS-native tools -- sips builds the @1x/@2x
# pair at every size an .iconset needs, iconutil packs the folder. No ImageMagick: its ICNS writer
# emits a single-resolution file, which Finder and the Dock then rescale badly.
%.icns: %.png
	rm -rf "$(@D)/$(*F).iconset"
	mkdir -p "$(@D)/$(*F).iconset"
	for size in 16 32 64 128 256 512; do \
		sips -z $$size $$size $< --out "$(@D)/$(*F).iconset/icon_$${size}x$${size}.png" >/dev/null; \
		double=$$((size * 2)); \
		sips -z $$double $$double $< --out "$(@D)/$(*F).iconset/icon_$${size}x$${size}@2x.png" >/dev/null; \
	done
	iconutil -c icns "$(@D)/$(*F).iconset" -o $@
	rm -rf "$(@D)/$(*F).iconset"

# Rendered at 2x the nominal 493x312 / 493x58. Every WixUI bitmap control has FixedSize unset
# (verified by querying the built MSI's Control table), so MSI *stretches* the bitmap to the
# control -- which on a 125%-scaled display means upscaling a 493px-wide raster to ~616px, and that
# is what made the mark look blurry. At 2x the same control size is reached by scaling *down*
# instead, which stays sharp; the cost is ~2 MB of BMP in a 215 MB installer.
#
# WiX draws the 493x312 background on the Welcome and Finish pages, with its own white text area
# covering everything past the left ~164px -- so the brand lives in that strip and the rest stays
# white. The icon's own slate rounded square is the exact same #37474F as the strip, so it dissolves
# into it and only the three bars read: the mark, not a pasted-on logo. BMP3 (24-bit, uncompressed)
# because WiX will not read PNG, and -alpha remove because it will not read an alpha channel either.
$(INSTALLER_DIR)/background.bmp: $(ICON_DIR)/rehuco-agent.png
	mkdir -p $(@D)
	magick -size 986x624 xc:white \
		\( -size 328x624 xc:"#37474F" \) -geometry +0+0 -composite \
		\( $< -resize 224x224 \) -geometry +52+144 -composite \
		-alpha remove BMP3:$@

# The 493x58 strip along the top of every other page: white, with the mark right-aligned where WiX
# put its own, at the 44px the 58px-tall banner leaves room for.
$(INSTALLER_DIR)/banner.bmp: $(ICON_DIR)/rehuco-agent.png
	mkdir -p $(@D)
	magick -size 986x116 xc:white \
		\( $< -resize 88x88 \) -geometry +884+14 -composite \
		-alpha remove BMP3:$@

# The docs site can't read outside docs_dir, so copy favicon + logo in. Real file targets give
# the newer-than behaviour for free: make re-copies only when the design/icons source changed.
# mkdir -p because these two are the only things in that directory and both are gitignored, so a
# fresh checkout does not have it -- git tracks files, not directories.
$(DOCS_IMAGES)/favicon.svg: $(ICON_DIR)/favicon.svg
	mkdir -p $(@D)
	cp $< $@

$(DOCS_IMAGES)/logo.svg: $(ICON_DIR)/rehuco-agent.svg
	mkdir -p $(@D)
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
	uv run bandit -c pyproject.toml -r packages/

pyright:
	uv run pyright packages/ tools/

pylint:
	uv run pylint packages/ tools/

check-slugs:
	uv run python tools/check_slug_refs.py

qa: format check-slugs cov bandit pyright pylint

# Both docs targets depend on docs-icons because the favicon and logo are generated, not committed:
# mkdocs-material resolves theme.favicon/theme.logo relative to docs_dir and cannot read outside it,
# so the design masters have to be copied in first. A bare `uv run mkdocs serve` on a fresh checkout
# will render without them until this has run once.
docs-serve: docs-icons
	uv run mkdocs serve

# --strict, so a broken internal link or a page missing from the nav fails instead of warning: both
# are invisible in `docs-serve` (which happily renders an unreachable page) and only show up once
# the site is published. Deliberately not part of `qa` -- mkdocs-puml renders diagrams through a
# PlantUML server, so a cold cache makes this need the network, which `qa` must not.
docs-build: docs-icons
	uv run mkdocs build --strict

# agent-dev-*: Windows-only, dev-only (packages/rehuco-agent/launcher) -- a local double-click/registration
# target with correct app identity, running the live editable install. Requires VS2022 and
# `cmake` on PATH (`scoop install cmake` if missing -- see packages/rehuco-agent/launcher/README.md).
# Never touched by qa/tests/publish or a real Briefcase build. Build output goes in .build/,
# mirroring the source path, alongside this repo's other generated-artifact dot-dirs (.dist/ etc).
AGENT_DEV_BUILD := .build/packages/rehuco-agent/launcher
AGENT_DEV_EXE := $(AGENT_DEV_BUILD)/Release/rehuco-agent-dev.exe

AGENT_DEV_SRC := packages/rehuco-agent/launcher/launcher.c packages/rehuco-agent/launcher/CMakeLists.txt \
	packages/rehuco-agent/launcher/config.h.in packages/rehuco-agent/launcher/launcher.rc.in

# $(AGENT_DEV_EXE) (not agent-dev-build itself) is the real target, so make only re-invokes cmake
# when a source/icon actually changed -- cmake's own incremental build already no-ops
# correctly, but agent-dev-build was PHONY, so make re-ran the (admittedly then-fast) cmake
# configure+build every time regardless. Depends on $(ICON_FILES) directly, not the `icons`
# label -- `icons` is itself PHONY, and a real target depending on a phony one is always
# considered out of date, which would defeat this whole fix. launcher.rc.in embeds the .ico
# into the exe's PE resources at build time, so it must exist before cmake configures/builds,
# not just before registering.
agent-dev-build: $(AGENT_DEV_EXE)

$(AGENT_DEV_EXE): $(AGENT_DEV_SRC) $(ICON_FILES)
	cmake -S packages/rehuco-agent/launcher -B $(AGENT_DEV_BUILD) -G "Visual Studio 17 2022" -A x64
	cmake --build $(AGENT_DEV_BUILD) --config Release

agent-dev-clean:
	rm -rf $(AGENT_DEV_BUILD)

# --register/--unregister route through rehuco-agent-dev.exe itself (its entry script calls
# rehuco_agent.__main__:main(), same as the real packaged CLI) -- it registers itself, not the
# packaged rehuco-agent.exe, since __main__.main() keys off sys.argv[0].
agent-dev-register: agent-dev-build
	"$(AGENT_DEV_EXE)" --register

agent-dev-unregister: agent-dev-build
	"$(AGENT_DEV_EXE)" --unregister

# agent-dist-*: the shippable end-user artifact, Windows and macOS ([[packaging-deployment#app-identity]]) --
# unlike the dev launcher above, which stays the fast local loop and is never shipped. Briefcase
# picks the host platform itself, so the same four targets are the documented build sequence on
# both. Linux has no Briefcase artifact at all ([[packaging-deployment#linux-format]]).
#
# Briefcase reads the pyproject of the *current* directory, so it runs with cwd in the agent
# package -- while --project keeps uv resolving against the workspace root, so the shared .venv and
# the root's `packaging` group are what it gets. (Letting uv discover the project from the member
# directory instead would sync the environment down to that one member's dependencies, evicting
# pytest/ruff/mkdocs from the shared venv.) Never part of qa/tests/publish: each downloads a Python
# support package and pip-installs the whole Qt stack into the bundle, and agent-dist-package also
# fetches the WiX toolset.
#
# BRIEFCASE_ARGS forwards extra flags, e.g. `make agent-dist-package BRIEFCASE_ARGS=--adhoc-sign` for
# an unsigned macOS build (signing/notarization is deliberately unfiled,
# [[appendices.open-questions#still-open]]).
BRIEFCASE := uv run --group packaging --directory packages/rehuco-agent --project ../.. briefcase
BRIEFCASE_ARGS :=

# `uis` first: Briefcase copies src/rehuco_agent verbatim into the bundle, so the gitignored
# *_ui.py/*_rc.py must already exist -- a bundle built without them dies on the first import.
agent-dist-build: uis $(ICON_FILES) $(INSTALLER_IMAGES)
	$(BRIEFCASE) build $(BRIEFCASE_ARGS)

# Seconds, not minutes: re-syncs the sources into the bundle built above, without reinstalling the
# dependency tree ([[appendices.briefcase-packaging#build-and-iterate]]).
agent-dist-update: uis
	$(BRIEFCASE) update $(BRIEFCASE_ARGS)

agent-dist-package: uis $(ICON_FILES) $(INSTALLER_IMAGES)
	$(BRIEFCASE) package $(BRIEFCASE_ARGS)

agent-dist-clean:
	rm -rf packages/rehuco-agent/build packages/rehuco-agent/dist

# agent-appimage-*: the Linux artifact ([[packaging-deployment#linux-format]] point 5) -- a python-appimage
# recipe over a relocatable manylinux_2_28 CPython, never Briefcase's own AppImage backend (which reprocesses
# already-relocated PySide6 libraries and can break them, [[appendices.briefcase-packaging#linux-backends]]).
# Only built on a tagged release ([[appendices.continuous-integration#release-agent]]), so this target is not
# part of qa/tests/publish either -- it downloads a ~50 MB base runtime and pip-installs the whole Qt stack
# into it, same cost profile as agent-dist-build.
AGENT_APPIMAGE_DIR    := packages/rehuco-agent/appimage
AGENT_APPIMAGE_OUT    := .dist/appimage
# python-appimage's `-p` matches a *release tag* ("3.14"), not a patch version -- the runtime
# it resolves to (currently 3.14.6) is picked up from the release's own asset filenames.
AGENT_APPIMAGE_PYTHON := 3.14
AGENT_APPIMAGE        := $(AGENT_APPIMAGE_OUT)/rehuco-agent-x86_64.AppImage

PYTHON_APPIMAGE := uv run --group appimage --directory $(AGENT_APPIMAGE_OUT) python-appimage

# requirements.txt is generated, not committed (gitignored: machine-specific absolute paths). Each line is
# pip-installed *separately* by python-appimage, in order -- borco-core/rehuco-core/borco-pyside first (each
# from its own source tree, built on the fly by pip via hatchling) so that rehuco-agent's own install last
# finds all three already satisfied locally instead of reaching PyPI, where the same four names already exist
# as unrelated 0.0.x stub releases ([[packaging-deployment#linux-format]] point 5). Absolute paths are
# required: python-appimage pip-installs from a temporary build directory, so a relative path would resolve
# against the wrong cwd.
agent-appimage-build: uis $(ICON_FILES)
	cp $(ICON_DIR)/rehuco-agent.png $(AGENT_APPIMAGE_DIR)/rehuco-agent.png
	printf '%s\n' \
		"$(CURDIR)/packages/borco-core" \
		"$(CURDIR)/packages/rehuco-core" \
		"$(CURDIR)/packages/borco-pyside" \
		"$(CURDIR)/packages/rehuco-agent" \
		> $(AGENT_APPIMAGE_DIR)/requirements.txt
	mkdir -p $(AGENT_APPIMAGE_OUT)
	$(PYTHON_APPIMAGE) build app -p $(AGENT_APPIMAGE_PYTHON) $(CURDIR)/$(AGENT_APPIMAGE_DIR)
	mv $(AGENT_APPIMAGE_OUT)/Rehuco-*.AppImage $(AGENT_APPIMAGE)
	chmod +x $(AGENT_APPIMAGE)

agent-appimage-clean:
	rm -f $(AGENT_APPIMAGE_DIR)/rehuco-agent.png $(AGENT_APPIMAGE_DIR)/requirements.txt
	rm -rf $(AGENT_APPIMAGE_OUT)
