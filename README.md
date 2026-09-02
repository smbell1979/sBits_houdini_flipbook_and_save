# Houdini Flipbook and Save

`flipbook_and_save.py` provides a small menu that captures the current
Scene View exactly as displayed,
encodes the JPEG sequence to H.264 MP4 with FFmpeg, removes the temporary JPEGs,
and saves a snapshot of the current HIP scene in a `flipbook` folder beside the
scene.
The capture runs without prompts; configuration is available as a separate menu
action.

## Install as a Houdini package

1. Close Houdini.
2. Find your Houdini user preferences folder. On Windows this is normally
   `Documents/houdini<version>` (for example, `Documents/houdini22.0`).
3. Copy both folders inside `dist` into that preferences folder:
   - `packages`
   - `sBits_houdini_flipbook_and_save`
4. Start Houdini.

The resulting layout should be:

```text
Documents/houdini22.0/
├── packages/
│   └── sBits_houdini_flipbook_and_save.json
└── sBits_houdini_flipbook_and_save/
    ├── MainMenuCommon.xml
    └── scripts/python/flipbook_and_save.py
```

The package adds a top-level **sBits** menu containing
**Flipbook and Save...**. Selecting it opens a small menu with
**Flipbook and Save** and **Configure…**. The capture action runs
without dialogs. The configurator saves preferences to
`$HOUDINI_USER_PREF_DIR/flipbook_and_save.json`, keeping them outside the scene
and project storage.

When the desktop contains multiple visible Scene Viewer panes—for example, a
pane layout split into separate Scene Viewers—the **Flipbook and Save** item
becomes a submenu listing every visible viewer in screen order, along with its
pane and viewport names. Choose the specific Scene Viewer to capture. This is distinct
from multiple viewports inside one Scene Viewer: the tool always captures only
the selected viewport for reliable, frame-complete output.

The HIP file must have been saved at least once. Output is created beside it:

```text
shot_010.hip
flipbook/
    shot_010_flipbook_20260718_103000_123456.mp4
    shot_010_flipbook_20260718_103000_123456_snapshot.hip
```

During capture, `$F4` JPEG frames are written into a unique local folder under
Houdini's `$HOUDINI_TEMP_DIR` (normally in Windows `%TEMP%`). Python's system
temporary directory is used as a fallback. This prevents intermediate frames
from being uploaded by synced or cloud-backed project storage such as
LucidLink. The temporary folder is removed after FFmpeg succeeds and retained
if encoding fails.

## FFmpeg setup and behavior

FFmpeg must provide the `ffmpeg` executable and the `libx264` encoder. The tool
looks for an encoder in this order:

1. `ffmpeg` available through the system `PATH` inherited by Houdini.
2. The explicit executable selected under **Configure… → FFmpeg fallback** or
   assigned to `FFMPEG_FALLBACK_PATH` in the script.

The `PATH` version is always preferred. If it cannot start or returns a failed
encode, the configured fallback is tried automatically. For example:

```python
FFMPEG_FALLBACK_PATH = r"C:\Tools\ffmpeg\bin\ffmpeg.exe"
```

If FFmpeg was added to the Windows `PATH` while Houdini was already running,
restart Houdini so the application inherits the updated environment. Setting
the explicit fallback path avoids requiring a restart or a system-wide PATH
change.

Movies use the current Houdini scene FPS and are encoded as H.264 with
`yuv420p` pixel format and fast-start metadata for broad playback compatibility.
`MP4_CRF` controls image quality: lower values increase quality and file size;
18 is the default. `MP4_PRESET` controls encoding speed versus compression but
does not directly control visual quality.

Temporary JPEGs are deleted only after a successful encode. If every FFmpeg
attempt fails, the JPEG sequence remains in `$HOUDINI_TEMP_DIR` and the debug
log records the executable, exit code, and FFmpeg output for each attempt.

Houdini's flipbook call is blocking: it returns after the capture has finished.
The tool then validates every expected numbered frame before launching FFmpeg.
If Houdini omits any frames, encoding stops, the exact missing frame numbers are
reported, and the temporary sequence is retained for diagnosis. Missing frames
are never silently replaced with duplicated images.

## Configuration

Use **Configure…** from the tool menu for the common settings. Defaults and
advanced options remain available as constants at the top of the script:

The **Intermediate images** setting offers JPEG for faster, smaller temporary
captures or PNG for lossless temporary frames. Both are encoded to the same MP4
output and follow the same cleanup and failure-recovery behavior.

- `RESOLUTION`: `(width, height)`, or `None` for current viewport size.
- `FRAME_RANGE`: `"playback"`, `"frame"`, or `(start, end)`.
- `FRAME_INCREMENT`: capture interval in frames.
- `IMAGE_FORMAT`: `"png"`, `"jpg"`, `"jpeg"`, or `"exr"`.
- `ANTIALIAS_SAMPLES`: `1`, `2`, `4`, or `8`; `None` uses the viewport setting.
- `OUTPUT_ZOOM_PERCENT`: output scaling from 1 to 100 percent.
- `OPEN_IN_MPLAY`: whether to also send frames to MPlay.
- `OUTPUT_LABEL`: label used in the output folder and filenames.
- `CREATE_MP4`: encode an H.264 movie using `ffmpeg` from the system `PATH`.
- `DELETE_IMAGES_AFTER_MP4`: remove source images after a successful encode.
- `MP4_CRF`: H.264 quality; lower is better quality and larger (`18` default).
- `MP4_PRESET`: encoding speed/compression tradeoff (`"medium"` default).
- `FFMPEG_FALLBACK_PATH`: optional explicit path to `ffmpeg.exe`. The executable
  from `PATH` is tried first; the fallback is tried if it cannot encode.
- `DEBUG_LOGGING`: writes progress and errors to a persistent text log inside
  the `flipbook` output folder. Logging is disabled by default.

JPEG is the default intermediate format for faster viewport capture. Houdini
controls JPEG compression through its image-output preferences. FFmpeg uses the
current Houdini scene FPS and produces a broadly compatible H.264/yuv420p MP4.
Temporary frames are retained if FFmpeg fails.

## Notes

- The current viewport, camera/view, shading, guides, visualizers, lighting,
  color correction, and other visible viewport state are used by the flipbook.
- Flipbook settings are copied before modification, so the interactive Flipbook
  dialog settings are not changed.
- The HIP snapshot includes current unsaved changes. Houdini remains pointed at
  the original HIP filename after the snapshot is written.

## Uninstall

Close Houdini, then remove these two items from the Houdini preferences folder:

- `packages/sBits_houdini_flipbook_and_save.json`
- `sBits_houdini_flipbook_and_save`

## Debugging

Progress appears in Houdini's status bar. When `DEBUG_LOGGING` is enabled, a
persistent `flipbook/flipbook_and_save_debug.log` is appended beside the current
HIP file. If the HIP has never been saved, the log is written to the operating
system's temporary folder instead. The log includes the full Python traceback
for any failure.

For the quickest test, temporarily use:

```python
FRAME_RANGE = "frame"
OPEN_IN_MPLAY = True
```

This captures one frame and makes a successful capture immediately visible in
MPlay. Also check whether the `flipbook` folder was created beside the HIP. If
the final MP4 is missing, the log identifies the operation or FFmpeg attempt
that failed, and the temporary JPEG folder is retained for recovery.
