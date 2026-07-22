# Houdini Flipbook and Save

`flipbook_and_save.py` provides a small shelf menu that captures the current
Scene View exactly as displayed,
encodes the JPEG sequence to H.264 MP4 with FFmpeg, removes the temporary JPEGs,
and saves a snapshot of the current HIP scene in a `flipbook` folder beside the
scene.
The capture runs without prompts; configuration is available as a separate menu
action.

## Install as a shelf tool

1. In Houdini, create a new shelf tool.
2. Set the tool's **Script Language** to **Python**.
3. Paste or load the complete contents of `flipbook_and_save.py` into the
   **Script** tab. Copy from the local `.py` file rather than rendered chat text.
4. Click the shelf tool while the mouse is over the Scene View you want to
   capture.

Clicking the shelf tool opens a menu with **Flipbook and Save** and
**Configure…**. The capture action runs without dialogs. The configurator saves
preferences to `$HOUDINI_USER_PREF_DIR/flipbook_and_save.json`, keeping them
outside the scene and project storage.

When the desktop contains multiple visible Scene Viewer panes—for example, a
pane layout split into separate Scene Viewers—the **Flipbook and Save** item
becomes a submenu listing every visible viewer in screen order, along with its
pane and viewport names. Choose the specific Scene Viewer to capture. This is distinct
from multiple viewports inside one Scene Viewer, which are controlled by
**Capture all visible viewports**.

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

Houdini may return from its flipbook API before the image writer has finished.
The tool therefore waits for the complete expected frame count before launching
FFmpeg while keeping Houdini's UI responsive. If no new frame appears for
`FLIPBOOK_STALL_TIMEOUT_SECONDS` (300 seconds by default), the run stops with a
clear error and retains the temporary folder for inspection.

## Configuration

Use **Configure…** from the shelf menu for the common settings. Defaults and
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
- `CAPTURE_ALL_VIEWPORTS`: capture the complete visible viewport layout. Keep
  this enabled for multiple viewports within one Scene Viewer. Separate Scene
  Viewer panes are selected from the shelf menu instead.
- `OUTPUT_LABEL`: label used in the output folder and filenames.
- `CREATE_MP4`: encode an H.264 movie using `ffmpeg` from the system `PATH`.
- `DELETE_IMAGES_AFTER_MP4`: remove source images after a successful encode.
- `MP4_CRF`: H.264 quality; lower is better quality and larger (`18` default).
- `MP4_PRESET`: encoding speed/compression tradeoff (`"medium"` default).
- `FFMPEG_FALLBACK_PATH`: optional explicit path to `ffmpeg.exe`. The executable
  from `PATH` is tried first; the fallback is tried if it cannot encode.
- `FLIPBOOK_STALL_TIMEOUT_SECONDS`: seconds without a newly written frame before
  treating the asynchronous viewport capture as stalled.
- `DEBUG_LOGGING`: writes progress and errors to a persistent text log.

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

## Debugging

Progress appears in Houdini's status bar. A persistent log named
`flipbook_and_save_debug.log` is appended beside the current HIP file. If the
HIP has never been saved, the log is written to the operating system's temporary
folder instead. The log includes the full Python traceback for any failure.

For the quickest test, temporarily use:

```python
FRAME_RANGE = "frame"
OPEN_IN_MPLAY = True
```

This captures one frame and makes a successful capture immediately visible in
MPlay. Also check whether the `flipbook` folder was created beside the HIP. If
the final MP4 is missing, the log identifies the operation or FFmpeg attempt
that failed, and the temporary JPEG folder is retained for recovery.
