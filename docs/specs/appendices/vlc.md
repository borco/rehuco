# VLC — python-vlc, Command Line and RC Interface

[[[appendices.vlc]]]

## Overview

[[[appendices.vlc#overview]]]

What was measured of the user's VLC 3.0.23 on Windows 11, for #319 ([[plugins#in-app-player]]). Two uses were
measured, and one of them was dropped:

- **libvlc in the player dock, through python-vlc** (section 5): what ships. python-vlc's import behaviour, the
  events and their threads, the snapshot that serves the paused still, what holds a file, and replaying after the end.
- **VLC launched as a process of its own and followed over its RC interface** (sections 1–4): built in #319 and
  removed in the same issue, once it was clear a separate window could carry none of the player's overlays. Kept
  for the record, since the facts were paid for and the RC route may be wanted elsewhere one day.

Everything was read with scratch scripts over three 8-second clips named `a one`, `b#two` and `c_ünï`, in a folder
with a `#` in its name. Transcripts are verbatim bar the file URI's folder, shortened to `F:/`. macOS and Linux are
untested.

## 1. Launching

[[[appendices.vlc#launch]]]

```text
vlc --no-one-instance --no-playlist-enqueue --qt-continue=0 --no-loop --no-repeat
    --extraintf=rc --rc-host=127.0.0.1:<port> --rc-quiet <playlist.m3u8>
```

- **`--no-one-instance`** opens a window of its own even when a VLC runs; without it the playlist would be handed to
  that VLC and the RC socket never opens. **`--no-playlist-enqueue`** keeps the playlist from joining another's.
- **`--qt-continue=0`** (*Never*) turns off VLC's own *continue where you left off* prompt, so it never fights the
  position the playlist starts each entry at.
- **`--no-loop --no-repeat`.** Left out, the playlist wraps: after the last entry ends, entry 1 starts again. With
  them the last entry ends in *stopped*.
- **`--rc-quiet`** is a Windows option (*Do not open a DOS command box interface*); it is passed only there.
- **The playlist** is UTF-8 `.m3u8`: `#EXTM3U`, then per entry `#EXTVLCOPT:start-time=<seconds>` and the file's URI
  (`Path.as_uri()`, which escapes `#` and spaces and spells a UNC path as `file://server/share/...`). The start time
  is honoured: an entry given `2.5` reported `get_time` 3 a second and a half after `goto`.
- **Cold start.** The RC port opened **12 s** after the launch on the first run, while VLC rebuilt its plugin cache,
  and **0.27 s** on later ones. Waiting for it has to be generous (30 s, as `VlcTool` allows the version read).

## 2. The playlist file is one element until it plays

[[[appendices.vlc#playlist-file]]]

Neither `--no-playlist-autostart` nor `--start-paused` can hold playback while the clicked entry is chosen. VLC
expands a playlist file only when it plays it: with autostart off, `goto 2` answers `Playlist has only 1 element`, and
with `--start-paused` the first entry opens paused and the `goto` is lost. So VLC starts on entry 1 and `goto <n>`
moves it once the socket connects. **Entry 1 can be heard briefly** before that, for as long as the port takes to open.
Nothing it plays is recorded: the tracker records an entry only after it has been seen to be the one asked for.
**A `goto` sent too early is lost**: connecting warm, within a fraction of a second, RC can answer before VLC has
expanded the file, and the `goto` is accepted (`returned 0`) but does nothing. The tracker therefore sends it again on
each poll until the entry asked for is the one named.

## 3. The RC protocol

[[[appendices.vlc#rc-protocol]]]

- **No greeting, no prompt.** With `--rc-quiet` nothing is sent on connect, and no `> ` prompt follows an answer.
- **Lines end in `\r\n`.** A command is a line ending in `\n`; several can be sent at once and answer in order.
- **Every command ends its answer with `<command>: returned 0 (no error)`.** `get_time`, `get_length` and `is_playing`
  are the exceptions: they answer a bare integer.
- **Asynchronous `status change: ( ... )` lines are mixed in anywhere**, before or after an answer: a new input, a
  play-state number, the volume, a pause, `( time: 6s )` after a seek. The numbers after `play state:` are not stable
  across a pause and a seek (`3` while playing, `2: Play` after a resume, `4: End` as an entry ends), so they are not
  read.
- **`goto <n>` is 1-based**, the order of the playlist. `seek <seconds>` takes whole seconds. `get_time` and
  `get_length` answer whole seconds.
- **`quit`** closes the socket (measured). VLC's window being closed was not measured; the tracker treats any closed
  socket as VLC having gone.

### The poll

[[[appendices.vlc#rc-poll]]]

One request, `status\nis_playing\nget_time\nget_length\n`, answers in three shapes. Playing, entry 2:

```text
status change: ( new input: F:/b%23two.mp4 )
status change: ( play state: 3 )
status: returned 0 (no error)
1
3
8
```

(the `1` is `is_playing`, then `get_time` 3, `get_length` 8). Paused: the answer names **no input**, and says so with
a line that is no `status change`:

```text
status change: ( pause state: 4 )
Type 'pause' to continue.
status: returned 0 (no error)
0
4
8
```

Stopped, whether by `stop` or by the last entry ending: a `stop state: 5` line, no input, and zeros.

```text
status change: ( audio volume: 243 )
status change: ( stop state: 5 )
status: returned 0 (no error)
0
0
0
```

So the parser reads: the **last `new input:` line** is the input; a `stop state: 5` line **after** it clears it and
means *stopped*; the **three bare integers** are `is_playing`, time and length. An answer with no input and not stopped
is a paused one, whose input stays the one before. An entry that has ended and been replaced shows as the next input,
with the `new input` line twice in one answer.

### The input URI

[[[appendices.vlc#input-uri]]]

`new input:` repeats the playlist's URI as VLC holds it: `file:///C:/.../clips%20%231/b%23two.mp4` and
`.../c_%C3%BCn%C3%AF.mp4`, percent-encoded as `Path.as_uri()` wrote them. It is matched to an entry by decoding it
(`urllib.parse.unquote`, `url2pathname`) and comparing the paths, case-folded on Windows. A UNC path was not measured;
the same decoding spells `file://server/share/x` as `//server/share/x`.

## 4. Behaviours worth knowing

[[[appendices.vlc#behaviours]]]

- **An entry ending moves on by itself**, and the poll sees the next input. The last position seen of the entry left is
  within one poll interval of its length, which is why reaching the end is judged with a tolerance, as the in-app
  player's is ([[field-schema#watch-progress]]).
- **`prev`** (VLC's button; `next` is the same) changes the input the same way `goto` does.
- **`seek` and `pause` toggle at once**; a `pause` while paused resumes.
- **A closed socket** is how the tracker learns VLC has gone; it makes its last flush there.

## 5. python-vlc and libvlc in-process

[[[appendices.vlc#python-vlc]]]

python-vlc 3.0.21203, LGPL-2.1+ by its metadata, is one file of `ctypes` bindings; it ships no VLC code and loads the
user's own `libvlc`. The agent reaches it only through `rehuco_core.VlcLibrary`, never by a plain `import vlc`,
because of what the import does.

### The import is the search

[[[appendices.vlc#python-vlc-import]]]

`find_lib()` runs at module import, and its outcomes were measured in child processes:

- **`PYTHON_VLC_LIB_PATH` set to the full `libvlc.dll` path**: a clean import, no search, no chdir, `vlc.dll._name`
  is that path. This is the only way the app imports it.
- **No variable, VLC installed**: found through the registry, PATH or `%ProgramFiles%\VideoLan\VLC`; while the DLL
  loads, python-vlc **`os.chdir`s the whole process** into VLC's folder and back. A second thread saw the VLC folder
  as its working directory during the import. In a process with pool threads that is a race.
- **No variable, no VLC findable** (registry key absent, no PATH entry, `PROGRAMFILES` pointing nowhere): it ends in
  `ctypes.CDLL(".\libvlc.dll")` relative to the working directory, and raises `FileNotFoundError` for
  `<cwd>\libvlc.dll`.
- **`PYTHON_VLC_LIB_PATH` naming a file that does not load**: `logger.error` and **`sys.exit(1)`** from inside the
  import. **`PYTHON_VLC_MODULE_PATH` naming no folder**: the same.
- **No `ProgramFiles` in the environment**: `KeyError` from inside the import.
- `vlc.Instance("--no-such-option")` answers `None`, not an exception (VLC prints *unknown option* to stderr).

So the proxy sets `PYTHON_VLC_LIB_PATH` to the library the Tools page resolved, imports inside
`try/except BaseException`, and a child process has imported the same library first, so a library that kills its
process kills the probe, not the app.

### Events and their threads

[[[appendices.vlc#python-vlc-events]]]

Measured with `set_hwnd` on a native `QWidget`, mouse and key input off, audio muted. Each event arrives on a
**libvlc thread of its own** (python-vlc's callbacks show as `Dummy-N`, a new one per event), except two that are
raised **synchronously on the thread that calls**: `MediaPlayerSnapshotTaken` inside `video_take_snapshot`, and
`MediaPlayerStopped` inside `stop()`. The order on `play()` of a local file:

```text
play() -> 0                      (returns at once)
Opening                          +1 ms
Buffering                        (many, with a percent)
LengthChanged                    +15 ms
Playing                          +17 ms
Vout                             +215 ms   first picture
PositionChanged, TimeChanged     then about every 500 ms
```

- **The snapshot is synchronous and works while paused**: `video_take_snapshot(0, path, 0, 0)` returned `0` after
  42 ms playing and 19 ms paused, the file written and the event raised before the call returned. So the paused still
  is taken on the pause, before the stop that lets the file go.
- **What holds the file**: renaming the clip's *folder* failed (*Access is denied*) while playing **and while
  paused**, and succeeded right after `stop()`, with the media still set, and after `set_media(None)`. Renaming the
  *file itself* succeeded even while paused (VLC opens it with delete sharing), which is not the case that matters:
  the app renames folders. So a paused video in the dock is a stopped player, as it is with Qt Multimedia.
- **`stop()` cost on the GUI thread**: 40–44 ms here (80–115 ms in #315's spike under a stream of time changes).
- **After the end**: `EndReached`, then `Vout` and `Stopped`; `get_state()` is `Ended`. A `play()` in that state
  returned `0` and did nothing (still `Ended` a second later). `stop()` then `play()` replays from the start.
- **`set_time()`** takes effect at once and raises its `TimeChanged` on the calling thread.
- **A snapshot draws on the picture** unless told not to: VLC's on-screen display says *Snapshot taken* and shows a
  thumbnail of it over the video. The instance is made with `--no-osd` and `--no-snapshot-preview` (and
  `--no-video-title-show`), so nothing of VLC's is ever drawn on the dock's surface.
- **A native window's picture can be read in memory on Windows**: `PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT)`
  returned libvlc's Direct3D picture -- playing and paused, on a monitor and off every monitor -- in 5--11 ms
  for 640x400. Measured while the engine still drew into a native window; superseded by section 6, where
  there is no window to read and the still is the last frame.
- **`vlc.EventType` members are not integers**: they are ctypes enumerations, `int(member)` raises, and the number
  is in `member.value`. Found by the first live run of the engine, after a fake built on `IntEnum` had hidden it; the
  engine's tests now fake the members the same way.
- **A folder rename is refused while libvlc plays or pauses, in the dock too** (the live run). The view's *paused is
  stopped* rule was applied to libvlc first, and **reopening and seeking landed a few frames off** on resume (seen by
  the owner), so under libvlc a pause now holds the file, paused on its frame, and the rename coordinator's
  before-rename call is what releases it.

### Drawing over the surface

[[[appendices.vlc#overlay]]]

What the maximized player's `I`, `T` and `N` overlays ([[plugins#player-maximized]]) will meet: libvlc draws into a
native child window, and Windows composes native windows, not Qt widgets. Measured with a label raised over a playing
surface and a screen grab of the window:

| Overlay | Result |
| --- | --- |
| An ordinary Qt widget, sibling of the surface | **a black hole**: the video is cut out under it and the label is not drawn |
| A sibling with a native window of its own, opaque | drawn over the video, opaque |
| The same native sibling, translucent (`WA_TranslucentBackground`) | not shown at all |
| A frameless, translucent top-level window placed over the surface | drawn over the video **with transparency** |

This is why libvlc renders into memory (section 6): the picture is then an ordinary widget and the table does not
apply to it. It still describes `QVideoWidget`, which holds a native window too, so the Qt engine is where libvlc
was until it, too, paints its frames (`QVideoSink` into the same painted surface) -- the thing to do before the
overlays are built ([[plugins#player-maximized]]).

## 6. Rendering into memory

[[[appendices.vlc#memory-rendering]]]

libvlc 3 has two outputs an application can use: a native window of its own (`set_hwnd`, `set_nsobject`,
`set_xwindow`) and **memory** (`video_set_callbacks` with `video_set_format_callbacks`); the OpenGL callbacks are
libvlc 4's. The dock uses memory, so that its picture is an ordinary widget.

- **The format callback cannot be written through python-vlc's prototype**: `VideoFormatCb` declares the chroma
  `c_char_p`, which ctypes hands over as copied bytes. A prototype of our own with `POINTER(c_char)`, cast to
  python-vlc's type where it is passed, lets `memmove` write `RV32` into it (measured: the callback then saw
  `640x384 I420` for a 640x360 clip and the frames came in 32-bit).
- **The picture size libvlc gives is the decoder's, padded** -- 384 lines for 360 -- so the frame is cropped to
  `video_get_size(0)` once that is known (it is `0x0` until the video plays).
- **One picture in the pool** (`setup` returns 1) means libvlc locks, writes, unlocks and displays each frame in turn,
  so copying the buffer inside the display callback, on libvlc's thread, is safe; the copy crosses to the GUI thread
  as a `QImage` through a queued signal and is painted by `QPainter`, scaled to fit.
- **Audio, the clock and subtitles stay libvlc's**: only the video output module is replaced. Frames are displayed at
  their presentation time against libvlc's audio clock; subtitles and anything else the video-output core blends
  arrive inside the frames (verified with an `.srt` beside a clip: its text was in the painted frame), which is why
  the instance is made with `--no-osd`.
- **The cost, measured** on a Ryzen 5 5600 with a 1080p60 clip in a window maximized on a 3440x1440 monitor
  (2752x1081 of picture): **59.3 fps**, the paint **2.6 ms** a frame, the whole process -- decoding included --
  **67 % of one core (6 % of the machine)**; 100 % of one core with smooth scaling, or with libvlc scaling to the
  window itself (an 11 MB buffer). Memory is one buffer of the picture's size (8 MB at 1080p) and the copies in
  flight.
- **What it changes for the player**: no native window, so any widget can be drawn over the picture; the still of a
  pause is the last frame, with no snapshot and no `PrintWindow`; and the engine is the same on every OS.
