# External Tools

Some programs rehuco can use do not ship with it: they are large, or their licence is one an installer of ours
should not carry. You install them yourself and point the app at them. This page says where each one comes from.

## FFmpeg, for video durations {#ffmpeg}

A tutorial's runtime is the sum of its videos' durations. **Settings ▸ Videos ▸ Duration probe** chooses what reads
them: **MediaInfo**, which ships with the app and needs nothing installed, or **FFmpeg (external)**, which uses the
`ffprobe` that comes with FFmpeg. The app looks for FFmpeg once, in the background, the first time it starts, and
remembers what it found. **Settings ▸ Tools** lists every install found (on `PATH`, or installed by winget, scoop,
Chocolatey, Homebrew or your distribution), each with its version and whether it works, and uses the newest that does
unless you pick another. **Custom** takes a path you browse to — the `ffmpeg` or `ffprobe` file, or the folder holding
them — and marks it *not found* if nothing usable is there. If you install
FFmpeg later, press **Detect** to look again. The *FFmpeg (external)* choice on the Videos page is available once one
does. Any FFmpeg from version 4.0 on works.

=== "Windows"

    ```powershell
    winget install Gyan.FFmpeg
    ```

    Or download a build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or
    [BtbN](https://github.com/BtbN/FFmpeg-Builds/releases), unpack it, and browse to `bin\ffprobe.exe`.

=== "macOS"

    ```bash
    brew install ffmpeg
    ```

=== "Linux"

    ```bash
    sudo apt install ffmpeg
    ```

    Or your distribution's own `ffmpeg` package.

Other builds are listed on [ffmpeg.org](https://ffmpeg.org/download.html).

## VLC, for playing videos in the app with VLC's own decoding {#vlc}

**Settings ▸ Videos ▸ Playback** chooses what decodes a video in the app's player: Qt's bundled FFmpeg, which
is always there, or **VLC (your own, in the app)**, which plays everything VLC plays, deinterlaced, with AV1
decoded in software on any graphics card. VLC's own window is not used: its library is loaded into the app's
player dock. The app looks for VLC once, in the background, together with FFmpeg, and **Settings ▸ Tools**
lists the usable installs found (on `PATH`, or in Program Files, scoop, `/Applications`, Homebrew or your
distribution's places) with their versions; an install that cannot be used -- too old, or without its shared
library, as a static or sandboxed build is -- is written to the log instead. The VLC choice is available once a
usable install is there; a VLC that goes missing after it was chosen keeps the choice selected and says why,
while videos play with Qt's decoding. If you install VLC later, press **Detect**. Any VLC from version 3.0 on
works, as long as it comes with its `libvlc` library, which the installers below do.

Install VLC from [videolan.org](https://www.videolan.org/vlc/):

=== "Windows"

    ```powershell
    winget install VideoLAN.VLC
    ```

=== "macOS"

    ```bash
    brew install --cask vlc
    ```

=== "Linux"

    ```bash
    sudo apt install vlc
    ```

## FFmpeg libraries, for AV1 in the app's player {#ffmpeg-libraries}

The app's own player decodes with the FFmpeg that ships inside Qt. That FFmpeg plays AV1 only on a graphics card
that decodes AV1 itself: Nvidia RTX 30 or later, recent AMD and Intel graphics, Apple M3 or later. On other machines
an AV1 video plays its sound with no picture. A **shared** FFmpeg build that includes the dav1d decoder fixes this:
the app loads its libraries instead of Qt's.

**Settings ▸ Videos ▸ Playback** chooses **Qt (bundled FFmpeg)** or **Qt with external FFmpeg libraries**. The
second is available once **Settings ▸ Tools** lists a build that works; it lists every build found, each with its
version and whether it works, and a build that cannot be used says why: a **static** build has no libraries to load,
another **major version** than Qt's cannot stand in for it, and a build for another processor will not load. The
libraries are loaded when the app starts, so a change takes effect at the **next start**; if the chosen build is gone
or fails to load, the app plays with Qt's own FFmpeg and the Videos page says why. When an AV1 video shows no
picture, the player's notice offers a button to the Tools page.

The build must match the FFmpeg the app's Qt was built with, by **major version**, and the machine's architecture
(`win64` on a 64-bit Intel or AMD Windows PC). A build that is not **shared** holds only `ffmpeg.exe` and
`ffprobe.exe`, with no libraries to load.

| The app's PySide6 | FFmpeg major | Libraries | Builds with dav1d |
| --- | --- | --- | --- |
| 6.11 | 7.1 | `avcodec-61.dll`, `avformat-61.dll`, `avutil-59.dll`, `swresample-5.dll`, `swscale-8.dll` | [BtbN 7.1.5 LGPL shared](https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-31-14-10/ffmpeg-n7.1.5-12-g1fdbca85aa-win64-lgpl-shared-7.1.zip) (BtbN's last 7.1 build); [gyan.dev 7.1.1 full shared](https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-full_build-shared.zip) (GPL) |
| 6.12 | 9.0 | `avcodec-63.dll`, `avformat-63.dll`, `avutil-61.dll`, `swresample-7.dll`, `swscale-10.dll` | [BtbN 9.0 LGPL shared](https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip) |

Only Windows has been tried, so only Windows offers the choice. Unpack the archive anywhere; the libraries are in its
`bin` folder. Winget installs one too: `winget install BtbN.FFmpeg.LGPL.Shared.7.1`.
