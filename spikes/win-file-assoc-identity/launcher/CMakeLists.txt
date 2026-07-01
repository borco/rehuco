cmake_minimum_required(VERSION 3.16)
project(rehuco-launcher C)

# Development.Embed = link Python as host (not extension module)
find_package(Python3 REQUIRED COMPONENTS Development.Embed)

# ---------------------------------------------------------------------------
# Venv Python path — baked into the binary at configure time via config.h.
#
# Separate from the Python used to compile (headers/lib above): that Python
# only needs its Include/ and .lib. The VENV_PYTHON below is what the launcher
# will actually exec at runtime — it must be the venv's python.exe so that
# pyvenv.cfg is found and the editable install is visible.
#
# For the real workspace the top-level CMakeLists.txt would derive this from
# CMAKE_SOURCE_DIR; here the spike venv sits one level above this CMakeLists.
# ---------------------------------------------------------------------------
set(VENV_PYTHON "${CMAKE_CURRENT_SOURCE_DIR}/../.venv/Scripts/python.exe"
    CACHE FILEPATH "Python executable the launcher will invoke at runtime")
get_filename_component(VENV_PYTHON "${VENV_PYTHON}" ABSOLUTE)   # resolve .. to a clean absolute path
file(TO_CMAKE_PATH "${VENV_PYTHON}" VENV_PYTHON_FWDSLASH)       # forward slashes — safe for Win32 APIs
configure_file(config.h.in "${CMAKE_CURRENT_BINARY_DIR}/config.h")

# Embed the absolute icon path so the RC compiler finds it regardless of working dir
set(ICON_ABS_PATH "${CMAKE_CURRENT_SOURCE_DIR}/../rehuco-spike.ico")
configure_file(launcher.rc.in "${CMAKE_CURRENT_BINARY_DIR}/launcher.rc")

# WIN32 entry-point = wWinMain, SUBSYSTEM:WINDOWS (no console flash)
add_executable(rehuco-launcher WIN32
    launcher.c
    "${CMAKE_CURRENT_BINARY_DIR}/launcher.rc"
)

target_include_directories(rehuco-launcher PRIVATE
    ${Python3_INCLUDE_DIRS}
    "${CMAKE_CURRENT_BINARY_DIR}"   # config.h lives here
)
target_link_libraries(rehuco-launcher PRIVATE ${Python3_LIBRARIES} shell32)

# Place the exe next to .venv/ so find_venv_python() resolves .venv\Scripts\python.exe
set(_OUT "${CMAKE_CURRENT_SOURCE_DIR}/..")
set_target_properties(rehuco-launcher PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY         "${_OUT}"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${_OUT}"
    RUNTIME_OUTPUT_DIRECTORY_DEBUG   "${_OUT}"
)
