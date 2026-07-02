# Dev-only launcher (see launcher.c) -- never invoked by `make publish` or a Briefcase build.
cmake_minimum_required(VERSION 3.16)
project(rehuco-agent-dev-launcher C)

# ---------------------------------------------------------------------------
# Workspace venv Python path -- two separate uses:
#  1. Below: a Python3_EXECUTABLE hint for find_package(Python3), so it locates the *build-time*
#     headers/import lib to compile against (requires a reasonably recent CMake -- Qt's bundled
#     3.30 predates Python 3.14 in its name-based search list; scoop's does not).
#  2. Baked into config.h (VENV_PYTHON_EXECUTABLE) for launcher.c to use as the *runtime*
#     interpreter -- config.executable and the "does the venv exist" check.
# Same venv, different mechanisms; ABSOLUTE + forward-slash conversion because the runtime one
# ends up as a literal wide-string in the compiled exe, so it must not depend on launch-time CWD.
# ---------------------------------------------------------------------------
set(VENV_PYTHON "${CMAKE_CURRENT_SOURCE_DIR}/../../../.venv/Scripts/python.exe"
    CACHE FILEPATH "Python executable the launcher will invoke at runtime")
get_filename_component(VENV_PYTHON "${VENV_PYTHON}" ABSOLUTE)   # resolve .. to a clean absolute path
file(TO_CMAKE_PATH "${VENV_PYTHON}" VENV_PYTHON_FWDSLASH)       # forward slashes -- safe for Win32 APIs

# CPython's own pyvenv.cfg auto-detection (config.executable/program_name, __PYVENV_LAUNCHER__)
# does not reliably activate this venv when embedding via Py_InitializeFromConfig on this
# CPython 3.14 build (confirmed environment-level: the pre-existing spike's own exe fails
# identically, and a freshly recreated .venv made no difference). Working around it directly:
# bake in site-packages and have launcher.c call site.addsitedir() on it explicitly.
get_filename_component(VENV_SITE_PACKAGES "${CMAKE_CURRENT_SOURCE_DIR}/../../../.venv/Lib/site-packages" ABSOLUTE)
file(TO_CMAKE_PATH "${VENV_SITE_PACKAGES}" VENV_SITE_PACKAGES_FWDSLASH)

configure_file(config.h.in "${CMAKE_CURRENT_BINARY_DIR}/config.h")

set(Python3_FIND_VIRTUALENV FIRST)
set(Python3_EXECUTABLE "${VENV_PYTHON}")
# Development.Embed = link Python as host (not extension module)
find_package(Python3 REQUIRED COMPONENTS Development.Embed)

# Embed the absolute icon path so the RC compiler finds it regardless of working dir.
# Built by `make icons` from the Affinity-Designer-authored svg master -- run that first.
set(ICON_ABS_PATH "${CMAKE_CURRENT_SOURCE_DIR}/../src/rehuco_agent/icons/rehuco-agent.ico")
configure_file(launcher.rc.in "${CMAKE_CURRENT_BINARY_DIR}/launcher.rc")

# WIN32 entry-point = wWinMain, SUBSYSTEM:WINDOWS (no console flash)
add_executable(rehuco-agent-dev WIN32
    launcher.c
    "${CMAKE_CURRENT_BINARY_DIR}/launcher.rc"
)

target_include_directories(rehuco-agent-dev PRIVATE
    ${Python3_INCLUDE_DIRS}
    "${CMAKE_CURRENT_BINARY_DIR}"   # config.h lives here
)
target_link_libraries(rehuco-agent-dev PRIVATE ${Python3_LIBRARIES} shell32)
